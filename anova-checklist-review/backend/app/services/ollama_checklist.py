"""Ollama JSON-schema checklist evaluator (concurrency 1).

LLM may only cite provided evidence IDs. Confidence is never auto-approve.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
from pydantic import BaseModel, Field, ValidationError, field_validator

from app.core.config import Settings
from app.core.enums import ChecklistAnswerState

_ollama_lock = asyncio.Lock()

LLM_ANSWER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["answer", "rationale", "subchecks", "evidence_ids", "inapplicability_rationale"],
    "properties": {
        "answer": {
            "type": "string",
            "enum": ["YES", "NO", "NA", "INSUFFICIENT_EVIDENCE", "MANUAL_REVIEW", "ERROR"],
        },
        "rationale": {"type": "string"},
        "subchecks": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "passed", "detail"],
                "properties": {
                    "id": {"type": "string"},
                    "passed": {"type": "boolean"},
                    "detail": {"type": "string"},
                },
            },
        },
        "evidence_ids": {"type": "array", "items": {"type": "string"}},
        "inapplicability_rationale": {"type": ["string", "null"]},
        "chapter": {"type": ["string", "null"]},
        "comment": {"type": ["string", "null"]},
        "confidence": {"type": "number"},
    },
}


class SubcheckResult(BaseModel):
    id: str
    passed: bool
    detail: str = ""


class LLMChecklistProposal(BaseModel):
    answer: ChecklistAnswerState
    rationale: str
    subchecks: list[SubcheckResult] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    inapplicability_rationale: str | None = None
    chapter: str | None = None
    comment: str | None = None
    confidence: float | None = None

    @field_validator("answer", mode="before")
    @classmethod
    def _coerce_answer(cls, v: Any) -> Any:
        if isinstance(v, str):
            return v.upper()
        return v


SYSTEM_PROMPT = """You are a software quality checklist assistant.
You MUST answer ONLY with a JSON object matching the provided schema.
You may ONLY cite evidence_ids from the provided evidence list — never invent IDs.
Missing search hits must be INSUFFICIENT_EVIDENCE, not NO.
Missing evidence must not be answered as NA.
NA requires a non-empty inapplicability_rationale.
YES requires all listed subchecks passed with supporting evidence_ids.
Your confidence score is informational only and is NOT approval."""


async def ollama_checklist_evaluate(
    settings: Settings,
    *,
    question: str,
    acceptance_criteria: str,
    subchecks: list[dict[str, Any]],
    evidence: list[dict[str, Any]],
) -> LLMChecklistProposal:
    user = {
        "question": question,
        "acceptance_criteria": acceptance_criteria,
        "subchecks": subchecks,
        "evidence": evidence,
        "instructions": [
            "Cite only provided evidence_ids",
            "YES requires all subchecks passed",
            "NA needs inapplicability_rationale",
            "Do not use confidence as approval",
        ],
    }
    payload = {
        "model": settings.ollama_llm_model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(user, ensure_ascii=False)},
        ],
        "stream": False,
        "format": LLM_ANSWER_SCHEMA,
        "options": {"temperature": 0, "seed": 42, "num_ctx": 8192},
    }

    async with _ollama_lock:
        # Enforce v1 concurrency 1 even if callers forget
        if settings.ollama_max_concurrency != 1:
            # still serialize via lock; do not raise
            pass
        try:
            async with httpx.AsyncClient(timeout=180.0) as client:
                r = await client.post(
                    f"{settings.ollama_base_url.rstrip('/')}/api/chat", json=payload
                )
                r.raise_for_status()
                content = r.json()["message"]["content"]
        except Exception as exc:  # noqa: BLE001
            return LLMChecklistProposal(
                answer=ChecklistAnswerState.ERROR,
                rationale=f"Ollama request failed: {exc}",
                subchecks=[],
                evidence_ids=[],
                confidence=0.0,
            )

    try:
        data = json.loads(content) if isinstance(content, str) else content
        return LLMChecklistProposal.model_validate(data)
    except (json.JSONDecodeError, ValidationError) as exc:
        return LLMChecklistProposal(
            answer=ChecklistAnswerState.ERROR,
            rationale=f"Invalid model JSON: {exc}",
            evidence_ids=[],
            confidence=0.0,
        )
