from __future__ import annotations

import uuid
from pathlib import Path

from app.services.chunking import chunk_units
from app.services.extraction import ExtractedUnit, Locator
from app.services.storage import sha256_bytes, write_original


def test_sha256_stable():
    assert sha256_bytes(b"abc") == sha256_bytes(b"abc")
    assert sha256_bytes(b"abc") != sha256_bytes(b"abd")


def test_write_original_preserves_bytes(tmp_path: Path):
    project_id = uuid.uuid4()
    document_id = uuid.uuid4()
    version_id = uuid.uuid4()
    data = b"%PDF-1.4 fake"
    path, digest = write_original(
        tmp_path, project_id, document_id, version_id, "Spec Rev A.pdf", data
    )
    assert path.is_file()
    assert path.read_bytes() == data
    assert digest == sha256_bytes(data)
    assert "original__" in path.name
    # revision-separated path
    assert str(version_id) in str(path)


def test_chunk_units_overlap():
    units = [
        ExtractedUnit(text="a" * 800, locator=Locator(kind="pdf_page", page=1)),
        ExtractedUnit(text="b" * 800, locator=Locator(kind="pdf_page", page=2)),
    ]
    chunks = chunk_units(units, chunk_size=1000, overlap=100)
    assert len(chunks) >= 2
    assert chunks[0].chunk_index == 0
    assert chunks[0].locator.get("page") == 1
