from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
COMPOSE = ROOT / "docker-compose.yml"


def test_compose_project_name_and_isolation():
    raw = COMPOSE.read_text(encoding="utf-8")
    data = yaml.safe_load(raw)

    assert data["name"] == "anova-checklist-review"
    assert "network_mode: host" not in raw
    assert "container_name:" not in raw
    assert ":latest" not in raw

    services = data["services"]
    required = {"gateway", "api", "postgres", "qdrant", "ollama", "embedding"}
    assert required <= set(services)

    # Only gateway may publish ports
    for name, svc in services.items():
        ports = svc.get("ports") or []
        if name == "gateway":
            assert ports, "gateway must publish configurable host port"
        else:
            assert not ports, f"{name} must not publish host ports"

    # Volumes are project-scoped names
    volumes = data.get("volumes") or {}
    for key, meta in volumes.items():
        assert str(meta.get("name", "")).startswith("anova-checklist-review_"), key

    networks = data.get("networks") or {}
    assert "acr_net" in networks
    assert networks["acr_net"]["name"] == "anova-checklist-review_acr_net"


def test_compose_images_pinned():
    data = yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))
    for name, svc in data["services"].items():
        image = svc.get("image")
        if not image:
            continue
        assert ":" in image and not image.endswith(":latest"), name
