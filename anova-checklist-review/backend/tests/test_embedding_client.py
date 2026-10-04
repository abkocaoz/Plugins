from __future__ import annotations

import hashlib
import math
import re

import httpx
import pytest

from app.core.config import Settings
from app.services.embedding_client import EmbeddingClient, _normalize_sparse


def _dense(text: str, dim: int = 8) -> list[float]:
    vec = []
    for i in range(dim):
        digest = hashlib.sha256(text.encode() + i.to_bytes(4, "little")).digest()
        vec.append((digest[0] - 128) / 128.0)
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


@pytest.mark.asyncio
async def test_embedding_client_batches():
    settings = Settings(
        embedding_url="http://embedding.test",
        embedding_dim=8,
        embedding_batch_size=2,
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/embed"
        import json

        body = json.loads(request.content.decode())
        texts = body["texts"]
        return httpx.Response(
            200,
            json={
                "model_id": "BAAI/bge-m3",
                "dim": 8,
                "dense": [_dense(t) for t in texts],
                "sparse": [{"1": 1.0} for _ in texts],
                "loaded": False,
            },
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url=settings.embedding_url) as client:
        emb = EmbeddingClient(settings, client=client)
        out = await emb.embed(["a", "b", "c"])
    assert len(out) == 3
    assert len(out[0].dense) == 8
    assert out[0].sparse["1"] == 1.0


def test_normalize_sparse_indices_values():
    raw = {"indices": [10, 20], "values": [0.5, 1.5]}
    assert _normalize_sparse(raw) == {"10": 0.5, "20": 1.5}


def test_tokenize_ok():
    assert re.match(r"[A-Za-z0-9_]+", "hello_1")
