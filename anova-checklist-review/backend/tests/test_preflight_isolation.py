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


def test_smoke_pilot_script_exists_and_mentions_docker_failure():
    script = ROOT / "scripts" / "smoke_pilot.sh"
    assert script.is_file()
    text = script.read_text(encoding="utf-8")
    assert "SMOKE FAILED: Docker is not installed" in text
    assert "anova-checklist-review" in text
