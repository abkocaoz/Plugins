"""HTTP client for the separate BGE-M3 embedding service (dense + sparse)."""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.core.config import Settings


@dataclass
class HybridEmbedding:
    dense: list[float]
    sparse: dict[str, float]


class EmbeddingClient:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.settings = settings
        self._client = client
        self._owns_client = client is None

    async def __aenter__(self) -> EmbeddingClient:
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self.settings.embedding_url, timeout=120.0)
        return self

    async def __aexit__(self, *args: object) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("EmbeddingClient not started; use 'async with'")
        return self._client

    async def health(self) -> dict:
        r = await self.client.get("/health")
        r.raise_for_status()
        return r.json()

    async def embed(self, texts: list[str]) -> list[HybridEmbedding]:
        if not texts:
            return []
        out: list[HybridEmbedding] = []
        batch = max(1, self.settings.embedding_batch_size)
        for i in range(0, len(texts), batch):
            payload = {"texts": texts[i : i + batch]}
            r = await self.client.post("/v1/embed", json=payload)
            r.raise_for_status()
            body = r.json()
            dense_list = body.get("dense") or []
            sparse_list = body.get("sparse") or []
            if len(dense_list) != len(payload["texts"]):
                raise RuntimeError(
                    f"Embedding service returned {len(dense_list)} dense vectors "
                    f"for {len(payload['texts'])} texts"
                )
            for d, s in zip(dense_list, sparse_list, strict=False):
                if len(d) != self.settings.embedding_dim:
                    raise RuntimeError(
                        f"Expected dense dim {self.settings.embedding_dim}, got {len(d)}"
                    )
                # sparse may be {token: weight} or {indices:[], values:[]}
                sparse_map = _normalize_sparse(s)
                out.append(HybridEmbedding(dense=list(d), sparse=sparse_map))
        return out


def _normalize_sparse(raw: object) -> dict[str, float]:
    if raw is None:
        return {}
    if isinstance(raw, dict):
        if "indices" in raw and "values" in raw:
            indices = raw.get("indices") or []
            values = raw.get("values") or []
            return {str(i): float(v) for i, v in zip(indices, values, strict=False)}
        return {str(k): float(v) for k, v in raw.items()}
    return {}
