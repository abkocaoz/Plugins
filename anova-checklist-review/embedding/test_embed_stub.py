"""Lightweight checks for the embedding stub (no FlagEmbedding required)."""

from __future__ import annotations

import os

os.environ["EMBEDDING_LOAD_MODEL"] = "0"
os.environ["EMBEDDING_DIM"] = "32"

from fastapi.testclient import TestClient

import app as embedding_app


def test_deterministic_hybrid_vectors():
    client = TestClient(embedding_app.app)
    r = client.post("/v1/embed", json={"texts": ["hello world", "hello world"]})
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "deterministic_stub"
    assert body["dim"] == 32
    assert len(body["dense"][0]) == 32
    assert body["dense"][0] == body["dense"][1]
    assert body["sparse"][0]
    # vectors are normalized (approx unit length)
    norm = sum(v * v for v in body["dense"][0]) ** 0.5
    assert 0.99 <= norm <= 1.01


def test_health():
    client = TestClient(embedding_app.app)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["service"] == "embedding"
