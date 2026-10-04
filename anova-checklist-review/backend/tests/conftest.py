from __future__ import annotations

import os

# Disable in-process worker for unit tests (no Postgres/Qdrant required).
os.environ.setdefault("WORKER_ENABLED", "false")
os.environ.setdefault("AUTH_MODE", "open")
os.environ.setdefault("UPLOAD_DIR", "/tmp/acr-test-uploads")
os.environ.setdefault("EXPORT_DIR", "/tmp/acr-test-exports")

from app.core.config import get_settings  # noqa: E402

get_settings.cache_clear()
