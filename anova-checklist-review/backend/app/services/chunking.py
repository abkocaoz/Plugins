"""Chunk extracted units for embedding / Qdrant upsert."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.services.extraction import ExtractedUnit


@dataclass
class TextChunk:
    chunk_index: int
    text: str
    locator: dict[str, Any]
    source_unit_indexes: list[int]


def chunk_units(
    units: list[ExtractedUnit],
    chunk_size: int = 1200,
    overlap: int = 150,
) -> list[TextChunk]:
    """Greedy pack units into overlapping character windows."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    overlap = max(0, min(overlap, chunk_size - 1))

    packed: list[TextChunk] = []
    buf = ""
    buf_units: list[int] = []
    buf_locator: dict[str, Any] = {}

    def flush() -> None:
        nonlocal buf, buf_units, buf_locator
        text = buf.strip()
        if not text:
            buf = ""
            buf_units = []
            return
        packed.append(
            TextChunk(
                chunk_index=len(packed),
                text=text,
                locator=dict(buf_locator),
                source_unit_indexes=list(buf_units),
            )
        )
        if overlap and len(text) > overlap:
            buf = text[-overlap:]
            # Keep last unit index as continuity hint
            buf_units = buf_units[-1:] if buf_units else []
        else:
            buf = ""
            buf_units = []

    for idx, unit in enumerate(units):
        piece = (unit.text or "").strip()
        if not piece:
            continue
        loc = unit.locator.to_dict()
        if not buf:
            buf_locator = loc
        candidate = piece if not buf else f"{buf}\n{piece}"
        if len(candidate) <= chunk_size:
            buf = candidate
            buf_units.append(idx)
            continue
        # Current buffer full enough — flush, then place piece (possibly split)
        if buf:
            flush()
        if len(piece) <= chunk_size:
            buf = piece
            buf_units = [idx]
            buf_locator = loc
            continue
        start = 0
        while start < len(piece):
            end = start + chunk_size
            segment = piece[start:end]
            packed.append(
                TextChunk(
                    chunk_index=len(packed),
                    text=segment,
                    locator={**loc, "char_start": start, "char_end": min(end, len(piece))},
                    source_unit_indexes=[idx],
                )
            )
            if end >= len(piece):
                break
            start = max(end - overlap, start + 1)
        buf = ""
        buf_units = []

    if buf.strip():
        flush()
    return packed
