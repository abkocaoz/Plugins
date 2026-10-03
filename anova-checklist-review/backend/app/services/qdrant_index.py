"""Qdrant collection ensure + hybrid upsert for standards / project docs."""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

from qdrant_client import QdrantClient
from qdrant_client.http import models as qm

from app.core.config import Settings
from app.services.chunking import TextChunk
from app.services.embedding_client import HybridEmbedding

DENSE_VECTOR_NAME = "dense"
SPARSE_VECTOR_NAME = "sparse"

PROJECT_DOC_PAYLOAD_INDEXES = [
    ("project_id", qm.PayloadSchemaType.KEYWORD),
    ("document_id", qm.PayloadSchemaType.KEYWORD),
    ("document_version_id", qm.PayloadSchemaType.KEYWORD),
    ("doc_type", qm.PayloadSchemaType.KEYWORD),
    ("content_sha256", qm.PayloadSchemaType.KEYWORD),
    ("version_label", qm.PayloadSchemaType.KEYWORD),
    ("chunk_index", qm.PayloadSchemaType.INTEGER),
]

STANDARD_PAYLOAD_INDEXES = [
    ("standard_id", qm.PayloadSchemaType.KEYWORD),
    ("standard_version_id", qm.PayloadSchemaType.KEYWORD),
    ("document_version_id", qm.PayloadSchemaType.KEYWORD),
    ("canonical_key", qm.PayloadSchemaType.KEYWORD),
    ("content_sha256", qm.PayloadSchemaType.KEYWORD),
    ("version_label", qm.PayloadSchemaType.KEYWORD),
    ("chunk_index", qm.PayloadSchemaType.INTEGER),
]


def point_id_for(collection_hint: str, version_id: uuid.UUID, chunk_index: int) -> str:
    raw = f"{collection_hint}:{version_id}:{chunk_index}".encode()
    return str(uuid.UUID(bytes=hashlib.sha256(raw).digest()[:16]))


class QdrantIndexer:
    def __init__(self, settings: Settings, client: QdrantClient | None = None):
        self.settings = settings
        self.client = client or QdrantClient(url=settings.qdrant_url, prefer_grpc=False)

    def ensure_collections(self) -> None:
        self._ensure_collection(
            self.settings.qdrant_collection_project_docs, PROJECT_DOC_PAYLOAD_INDEXES
        )
        self._ensure_collection(
            self.settings.qdrant_collection_standards, STANDARD_PAYLOAD_INDEXES
        )

    def _ensure_collection(
        self,
        name: str,
        indexes: list[tuple[str, qm.PayloadSchemaType]],
    ) -> None:
        existing = {c.name for c in self.client.get_collections().collections}
        if name not in existing:
            self.client.create_collection(
                collection_name=name,
                vectors_config={
                    DENSE_VECTOR_NAME: qm.VectorParams(
                        size=self.settings.embedding_dim,
                        distance=qm.Distance.COSINE,
                    )
                },
                sparse_vectors_config={
                    SPARSE_VECTOR_NAME: qm.SparseVectorParams(
                        index=qm.SparseIndexParams(on_disk=False)
                    )
                },
            )
        for field, schema in indexes:
            try:
                self.client.create_payload_index(
                    collection_name=name,
                    field_name=field,
                    field_schema=schema,
                )
            except Exception:  # noqa: BLE001 — already exists is fine / version variance
                pass

    def delete_by_document_version(self, collection: str, document_version_id: uuid.UUID) -> None:
        self.client.delete(
            collection_name=collection,
            points_selector=qm.FilterSelector(
                filter=qm.Filter(
                    must=[
                        qm.FieldCondition(
                            key="document_version_id",
                            match=qm.MatchValue(value=str(document_version_id)),
                        )
                    ]
                )
            ),
        )

    def upsert_project_document_chunks(
        self,
        *,
        project_id: uuid.UUID,
        document_id: uuid.UUID,
        document_version_id: uuid.UUID,
        doc_type: str,
        version_label: str,
        content_sha256: str,
        chunks: list[TextChunk],
        embeddings: list[HybridEmbedding],
    ) -> int:
        if len(chunks) != len(embeddings):
            raise ValueError("chunks/embeddings length mismatch")
        collection = self.settings.qdrant_collection_project_docs
        self.ensure_collections()
        self.delete_by_document_version(collection, document_version_id)
        points = []
        for chunk, emb in zip(chunks, embeddings, strict=True):
            pid = point_id_for("proj", document_version_id, chunk.chunk_index)
            payload = {
                "project_id": str(project_id),
                "document_id": str(document_id),
                "document_version_id": str(document_version_id),
                "doc_type": doc_type,
                "version_label": version_label,
                "content_sha256": content_sha256,
                "chunk_index": chunk.chunk_index,
                "locator": chunk.locator,
                "text": chunk.text,
                "text_preview": chunk.text[:280],
            }
            points.append(self._point(pid, emb, payload))
        if points:
            self.client.upsert(collection_name=collection, points=points)
        return len(points)

    def upsert_standard_chunks(
        self,
        *,
        standard_id: uuid.UUID,
        standard_version_id: uuid.UUID,
        document_version_id: uuid.UUID | None,
        canonical_key: str,
        version_label: str,
        content_sha256: str,
        chunks: list[TextChunk],
        embeddings: list[HybridEmbedding],
    ) -> int:
        if len(chunks) != len(embeddings):
            raise ValueError("chunks/embeddings length mismatch")
        collection = self.settings.qdrant_collection_standards
        self.ensure_collections()
        if document_version_id is not None:
            self.delete_by_document_version(collection, document_version_id)
        else:
            # delete by standard_version_id
            self.client.delete(
                collection_name=collection,
                points_selector=qm.FilterSelector(
                    filter=qm.Filter(
                        must=[
                            qm.FieldCondition(
                                key="standard_version_id",
                                match=qm.MatchValue(value=str(standard_version_id)),
                            )
                        ]
                    )
                ),
            )
        points = []
        version_key = document_version_id or standard_version_id
        for chunk, emb in zip(chunks, embeddings, strict=True):
            pid = point_id_for("std", version_key, chunk.chunk_index)
            payload = {
                "standard_id": str(standard_id),
                "standard_version_id": str(standard_version_id),
                "document_version_id": str(document_version_id) if document_version_id else None,
                "canonical_key": canonical_key,
                "version_label": version_label,
                "content_sha256": content_sha256,
                "chunk_index": chunk.chunk_index,
                "locator": chunk.locator,
                "text": chunk.text,
                "text_preview": chunk.text[:280],
            }
            points.append(self._point(pid, emb, payload))
        if points:
            self.client.upsert(collection_name=collection, points=points)
        return len(points)

    def _point(self, pid: str, emb: HybridEmbedding, payload: dict[str, Any]) -> qm.PointStruct:
        sparse_map = emb.sparse or {"0": 1.0}
        indices: list[int] = []
        values: list[float] = []
        for k, v in sparse_map.items():
            indices.append(int(k) if str(k).isdigit() else abs(hash(str(k))) % (2**31))
            values.append(float(v))
        sparse = qm.SparseVector(indices=indices, values=values)
        return qm.PointStruct(
            id=pid,
            payload=payload,
            vector={
                DENSE_VECTOR_NAME: emb.dense,
                SPARSE_VECTOR_NAME: sparse,
            },
        )
