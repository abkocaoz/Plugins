from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "preflight_check.py"


def _load():
    spec = importlib.util.spec_from_file_location("acr_preflight", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


def test_compose_isolation_function_passes():
    mod = _load()
    mod.check_compose_isolation()
