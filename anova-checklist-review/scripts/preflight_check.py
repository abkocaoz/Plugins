#!/usr/bin/env python3
"""Preflight / isolation checks for anova-checklist-review.

Run on the *deploy host* before `docker compose up`.
Fails loudly on conflicts or insufficient resources. Never stops other services.
"""

from __future__ import annotations

import argparse
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

PROJECT_NAME = "anova-checklist-review"
COMPOSE_FILE = Path(__file__).resolve().parents[1] / "docker-compose.yml"


class PreflightError(Exception):
    pass


def _load_dotenv(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.is_file():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def check_docker() -> None:
    if not shutil.which("docker"):
        raise PreflightError(
            "Docker is not installed or not on PATH. "
            "Install Docker Engine + Compose plugin on this host before deploying."
        )
    try:
        subprocess.run(
            ["docker", "info"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
    except subprocess.CalledProcessError as exc:
        raise PreflightError(f"Docker daemon not reachable: {exc.stderr.strip()}") from exc

    # Prefer `docker compose` plugin
    r = subprocess.run(["docker", "compose", "version"], capture_output=True, text=True)
    if r.returncode != 0:
        raise PreflightError("Docker Compose plugin missing (`docker compose version` failed).")


def port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1.0)
        return sock.connect_ex((host, port)) != 0


def check_gateway_port(bind: str, port: int) -> None:
    probe_host = "127.0.0.1" if bind in {"0.0.0.0", "::", ""} else bind
    if not port_free(probe_host, port):
        raise PreflightError(
            f"Gateway port {port} on {probe_host} is already in use. "
            f"Set GATEWAY_HOST_PORT to a free port. Refusing to bind."
        )


def check_resources(min_ram_gb: float, min_disk_gb: float, require_gpu: bool) -> None:
    # RAM
    meminfo = Path("/proc/meminfo")
    if meminfo.is_file():
        data = {}
        for line in meminfo.read_text().splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                data[k] = v.strip()
        # MemAvailable in kB
        avail_kb = float(data.get("MemAvailable", "0").split()[0])
        avail_gb = avail_kb / (1024 * 1024)
        if avail_gb < min_ram_gb:
            raise PreflightError(
                f"Insufficient available RAM: {avail_gb:.1f} GiB < required {min_ram_gb} GiB. "
                "Will not stop other services to free memory."
            )

    # Disk (project directory)
    usage = shutil.disk_usage(COMPOSE_FILE.parent)
    free_gb = usage.free / (1024**3)
    if free_gb < min_disk_gb:
        raise PreflightError(
            f"Insufficient free disk: {free_gb:.1f} GiB < required {min_disk_gb} GiB."
        )

    if require_gpu:
        if not shutil.which("nvidia-smi"):
            raise PreflightError(
                "PREFLIGHT_REQUIRE_GPU=1 but nvidia-smi not found. "
                "GPU isolation is not guaranteed by Compose networks."
            )


def check_compose_isolation() -> None:
    text = COMPOSE_FILE.read_text(encoding="utf-8")
    if "network_mode: host" in text or "network_mode:\"host\"" in text:
        raise PreflightError("Compose file must not use network_mode: host")
    if "container_name:" in text:
        raise PreflightError("Compose file must not set container_name (keep project-scoped names)")
    # Ensure infra ports are not published
    forbidden_publish_hints = [
        "5432:5432",
        "6333:6333",
        "6334:6334",
        "11434:11434",
        "8080:8080",  # embedding
    ]
    for hint in forbidden_publish_hints:
        if hint in text.replace(" ", ""):
            raise PreflightError(
                f"Forbidden host port publish detected near '{hint}'. "
                "Only the gateway may publish a host port."
            )
    if ":latest" in text:
        raise PreflightError("Pinned images required: found ':latest' in compose file")


def check_foreign_project_collision() -> None:
    """Warn/fail if volumes/networks with our exact names already exist from another stack."""
    r = subprocess.run(
        ["docker", "volume", "ls", "--format", "{{.Name}}"],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        return
    owned_prefix = f"{PROJECT_NAME}_"
    # Presence is OK if it belongs to this project; we only fail if user asked for fresh and conflict.
    # Soft check: list foreign-looking generic names we refuse to reuse.
    forbidden = {"postgres_data", "qdrant_storage", "ollama", "pgdata"}
    existing = set(r.stdout.split())
    collision = sorted(forbidden & existing)
    if collision:
        print(
            "WARNING: generic volume names exist on host "
            f"{collision}. This project uses only '{owned_prefix}*' volumes "
            "and will not mount those generics.",
            file=sys.stderr,
        )


def check_compose_config() -> None:
    env_file = COMPOSE_FILE.parent / ".env"
    cmd = [
        "docker",
        "compose",
        "-p",
        PROJECT_NAME,
        "-f",
        str(COMPOSE_FILE),
        "config",
        "-q",
    ]
    if env_file.is_file():
        cmd[2:2] = ["--env-file", str(env_file)]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=str(COMPOSE_FILE.parent))
    if r.returncode != 0:
        raise PreflightError(f"`docker compose config` failed:\n{r.stderr or r.stdout}")


def main() -> int:
    parser = argparse.ArgumentParser(description="anova-checklist-review preflight")
    parser.add_argument(
        "--env-file",
        default=str(COMPOSE_FILE.parent / ".env"),
        help="Path to .env (defaults to project .env; falls back to .env.example values)",
    )
    parser.add_argument("--skip-docker", action="store_true", help="Skip docker daemon checks (CI unit only)")
    args = parser.parse_args()

    env_path = Path(args.env_file)
    example = COMPOSE_FILE.parent / ".env.example"
    file_env = _load_dotenv(example)
    file_env.update(_load_dotenv(env_path))
    # process env wins
    merged = {**file_env, **os.environ}

    bind = merged.get("GATEWAY_BIND", "127.0.0.1")
    port = int(merged.get("GATEWAY_HOST_PORT", "18080"))
    min_ram = float(merged.get("PREFLIGHT_MIN_RAM_GB", "8"))
    min_disk = float(merged.get("PREFLIGHT_MIN_DISK_GB", "20"))
    require_gpu = merged.get("PREFLIGHT_REQUIRE_GPU", "0") in {"1", "true", "True"}

    print(f"Project: {PROJECT_NAME}")
    print(f"Compose: {COMPOSE_FILE}")
    print(f"Gateway candidate: {bind}:{port}")

    try:
        check_compose_isolation()
        print("OK compose isolation constraints")
        check_resources(min_ram, min_disk, require_gpu)
        print("OK resource gates")
        check_gateway_port(bind, port)
        print(f"OK gateway port free ({bind}:{port})")
        if not args.skip_docker:
            check_docker()
            print("OK docker + compose plugin")
            check_foreign_project_collision()
            check_compose_config()
            print("OK docker compose config")
        else:
            print("SKIP docker checks (--skip-docker)")
    except PreflightError as exc:
        print(f"PREFLIGHT FAILED: {exc}", file=sys.stderr)
        return 1

    print("PREFLIGHT PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
