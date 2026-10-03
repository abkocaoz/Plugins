"""BGE-M3 embedding HTTP service (Phase 1 skeleton).

Dense (1024) + sparse hybrid encoding will be enabled in Phase 2 when
EMBEDDING_LOAD_MODEL=1 and FlagEmbedding/BAAI-bge-m3 are installed on a
host with enough RAM/CPU (or CUDA). This process stays separate from Ollama.
"""

from __future__ import annotations

import os

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

MODEL_ID = os.getenv("EMBEDDING_MODEL_ID", "BAAI/bge-m3")
MODEL_REVISION = os.getenv("EMBEDDING_MODEL_REVISION", "") or None
DIM = int(os.getenv("EMBEDDING_DIM", "1024"))
DEVICE = os.getenv("EMBEDDING_DEVICE", "cpu")
LOAD_MODEL = os.getenv("EMBEDDING_LOAD_MODEL", "0") == "1"

app = FastAPI(title="acr-embedding", version="0.1.0")
_model = None


class EmbedRequest(BaseModel):
    texts: list[str] = Field(default_factory=list, max_length=64)


class EmbedResponse(BaseModel):
    model_id: str
    dim: int
    dense: list[list[float]]
    sparse: list[dict[str, float]]
    loaded: bool


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
    }


@app.post("/v1/embed", response_model=EmbedResponse)
def embed(req: EmbedRequest) -> EmbedResponse:
    if not LOAD_MODEL:
        # Phase 1: deterministic zero vectors so API wiring can be tested.
        n = len(req.texts)
        return EmbedResponse(
            model_id=MODEL_ID,
            dim=DIM,
            dense=[[0.0] * DIM for _ in range(n)],
            sparse=[{} for _ in range(n)],
            loaded=False,
        )
    raise HTTPException(
        status_code=501,
        detail="Model-backed embedding not enabled in this image build yet (Phase 2).",
    )
