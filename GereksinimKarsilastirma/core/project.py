"""Proje dosyası (JSON): setler, ayarlar, elle eşleştirmeler, kararlar, temel çizgi."""
from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from .compare import DEFAULT_SETTINGS
from .llm import DEFAULT_CHAT_MODEL, DEFAULT_EMBED_MODEL, DEFAULT_URL

PROJECTS_DIR = Path(__file__).resolve().parent.parent / "projeler"

STATUSES = ["Açık", "Düzeltilecek", "Kasıtlı fark", "Tamam"]


def new_project(name: str) -> dict:
    now = datetime.now().isoformat(timespec="seconds")
    return {
        "name": name,
        "created": now,
        "updated": now,
        "settings": dict(DEFAULT_SETTINGS),
        "llm": {"enabled": False, "url": DEFAULT_URL, "chat_model": DEFAULT_CHAT_MODEL,
                "embed_model": DEFAULT_EMBED_MODEL},
        "sets": {},
        "manual": {"merge": [], "detach": []},
        "decisions": {},
        "llm_notes": {},
        "llm_cache": {},
        "baseline": None,
        "history": [],
    }


def safe_name(name: str) -> str:
    return re.sub(r"[^\w\-. ]+", "_", name.strip(), flags=re.UNICODE) or "proje"


def project_path(name: str) -> Path:
    return PROJECTS_DIR / f"{safe_name(name)}.json"


def list_projects() -> list[str]:
    PROJECTS_DIR.mkdir(exist_ok=True)
    return sorted(p.stem for p in PROJECTS_DIR.glob("*.json"))


def save_project(p: dict) -> Path:
    PROJECTS_DIR.mkdir(exist_ok=True)
    p["updated"] = datetime.now().isoformat(timespec="seconds")
    path = project_path(p["name"])
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(p, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)
    return path


def load_project(name: str) -> dict:
    p = json.loads(project_path(name).read_text(encoding="utf-8"))
    base = new_project(p.get("name", name))
    for k, v in base.items():
        p.setdefault(k, v)
    p["settings"] = {**DEFAULT_SETTINGS, **p["settings"]}
    return p


def log(p: dict, event: str) -> None:
    p["history"].append({"tarih": datetime.now().isoformat(timespec="seconds"), "olay": event})
