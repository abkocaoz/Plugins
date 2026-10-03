from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.session import get_db

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(settings: Settings = Depends(get_settings)) -> dict:
    return {
        "status": "ok",
        "service": settings.app_name,
        "phase": 4,
        "worker_enabled": settings.worker_enabled,
    }


@router.get("/ready")
async def ready(
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    await db.execute(text("SELECT 1"))
    return {
        "status": "ready",
        "database": "ok",
        "qdrant_url": settings.qdrant_url,
        "ollama_base_url": settings.ollama_base_url,
        "embedding_url": settings.embedding_url,
        "ollama_max_concurrency": settings.ollama_max_concurrency,
        "collections": {
            "standards": settings.qdrant_collection_standards,
            "project_documents": settings.qdrant_collection_project_docs,
        },
    }


@router.get("/api/v1/meta")
async def meta(settings: Settings = Depends(get_settings)) -> dict:
    return {
        "app": settings.app_name,
        "auth_mode": settings.auth_mode,
        "embedding_model_id": settings.embedding_model_id,
        "embedding_dim": settings.embedding_dim,
        "llm_model": settings.ollama_llm_model,
        "reference_statuses": [
            "VERIFIED",
            "METADATA_MISMATCH",
            "VERSION_UNSPECIFIED",
            "VERSION_MISMATCH",
            "CLAUSE_NOT_FOUND",
            "CLAIM_NOT_SUPPORTED",
            "MISSING_SOURCE",
            "AMBIGUOUS_MATCH",
            "INSUFFICIENT_EVIDENCE",
            "MANUAL_REVIEW",
        ],
    }
