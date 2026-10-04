"""BGE-M3 embedding HTTP service (dense 1024 + sparse hybrid).

Default mode (EMBEDDING_LOAD_MODEL=0): deterministic hash-based vectors so the
API/indexer pipeline can be exercised without downloading multi-GB weights.

Real model mode (EMBEDDING_LOAD_MODEL=1): loads FlagEmbedding BGEM3FlagModel
when installed (see requirements-ml.txt). Remains a separate service from Ollama.
"""

from __future__ import annotations

import hashlib
import math
import os
import re
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

MODEL_ID = os.getenv("EMBEDDING_MODEL_ID", "BAAI/bge-m3")
MODEL_REVISION = os.getenv("EMBEDDING_MODEL_REVISION", "") or None
DIM = int(os.getenv("EMBEDDING_DIM", "1024"))
DEVICE = os.getenv("EMBEDDING_DEVICE", "cpu")
LOAD_MODEL = os.getenv("EMBEDDING_LOAD_MODEL", "0") == "1"

_model: Any = None
_TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


class EmbedRequest(BaseModel):
    texts: list[str] = Field(default_factory=list, max_length=64)


class EmbedResponse(BaseModel):
    model_id: str
    dim: int
    dense: list[list[float]]
    sparse: list[dict[str, float]]
    loaded: bool
    mode: str


def _deterministic_dense(text: str, dim: int) -> list[float]:
    vec = [0.0] * dim
    data = text.encode("utf-8")
    for i in range(dim):
        digest = hashlib.sha256(data + i.to_bytes(4, "little")).digest()
        vec[i] = (digest[0] - 128) / 128.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _deterministic_sparse(text: str) -> dict[str, float]:
    counts: dict[str, int] = {}
    for tok in _TOKEN_RE.findall(text.lower()):
        counts[tok] = counts.get(tok, 0) + 1
    if not counts:
        return {"0": 1.0}
    out: dict[str, float] = {}
    for tok, tf in counts.items():
        idx = int(hashlib.md5(tok.encode()).hexdigest()[:8], 16) % 100_000
        out[str(idx)] = float(tf)
    return out


def _ensure_model() -> Any:
    global _model
    if _model is not None:
        return _model
    try:
        from FlagEmbedding import BGEM3FlagModel  # type: ignore
    except ImportError as exc:
        raise HTTPException(
            status_code=501,
            detail=(
                "FlagEmbedding not installed in this image. "
                "Install embedding/requirements-ml.txt or keep EMBEDDING_LOAD_MODEL=0."
            ),
        ) from exc
    _model = BGEM3FlagModel(
        MODEL_ID,
        use_fp16=(DEVICE != "cpu"),
        device=DEVICE,
    )
    return _model


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if LOAD_MODEL:
        _ensure_model()
    yield


app = FastAPI(title="acr-embedding", version="0.2.0", lifespan=lifespan)


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "service": "embedding",
        "model_id": MODEL_ID,
        "model_revision": MODEL_REVISION,
        "dim": DIM,
        "device": DEVICE,
        "model_loaded": _model is not None,
        "load_model_flag": LOAD_MODEL,
        "mode": "bge-m3" if _model is not None else "deterministic_stub",
    }


@app.post("/v1/embed", response_model=EmbedResponse)
def embed(req: EmbedRequest) -> EmbedResponse:
    if not LOAD_MODEL:
        dense = [_deterministic_dense(t, DIM) for t in req.texts]
        sparse = [_deterministic_sparse(t) for t in req.texts]
        return EmbedResponse(
            model_id=MODEL_ID,
            dim=DIM,
            dense=dense,
            sparse=sparse,
            loaded=False,
            mode="deterministic_stub",
        )

    model = _ensure_model()
    try:
        out = model.encode(
            req.texts,
            return_dense=True,
            return_sparse=True,
            return_colbert_vecs=False,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"BGE-M3 encode failed: {exc}") from exc

    dense = [list(map(float, v)) for v in out["dense_vecs"]]
    sparse_list: list[dict[str, float]] = []
    for lexical in out.get("lexical_weights") or []:
        sparse_list.append({str(k): float(v) for k, v in dict(lexical).items()})
    return EmbedResponse(
        model_id=MODEL_ID,
        dim=DIM,
        dense=dense,
        sparse=sparse_list,
        loaded=True,
        mode="bge-m3",
    )
