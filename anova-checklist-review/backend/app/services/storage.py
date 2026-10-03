"""Original-file storage with SHA-256 and revision-separated paths."""

from __future__ import annotations

import hashlib
import re
import uuid
from pathlib import Path

_SAFE_RE = re.compile(r"[^A-Za-z0-9._-]+")


def safe_filename(name: str) -> str:
    base = Path(name or "upload.bin").name
    cleaned = _SAFE_RE.sub("_", base).strip("._") or "upload.bin"
    return cleaned[:180]


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def version_storage_dir(
    upload_root: Path,
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    version_id: uuid.UUID,
) -> Path:
    return upload_root / str(project_id) / str(document_id) / str(version_id)


def write_original(
    upload_root: Path,
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    original_filename: str,
    data: bytes,
) -> tuple[Path, str]:
    """Persist original bytes. Returns (absolute path, sha256)."""
    dest_dir = version_storage_dir(upload_root, project_id, document_id, version_id)
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / f"original__{safe_filename(original_filename)}"
    digest = sha256_bytes(data)
    dest.write_bytes(data)
    return dest, digest


def write_extraction_artifact(
    upload_root: Path,
    project_id: uuid.UUID,
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    relative_name: str,
    data: bytes,
) -> Path:
    dest_dir = version_storage_dir(upload_root, project_id, document_id, version_id) / "extracted"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / safe_filename(relative_name)
    dest.write_bytes(data)
    return dest
