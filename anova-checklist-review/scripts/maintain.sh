#!/usr/bin/env sh
# Scoped maintenance helpers — NEVER run global docker system prune from here.
set -eu
ROOT="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
PROJECT="anova-checklist-review"

cmd="${1:-ps}"
shift || true

case "$cmd" in
  ps|logs|up|down|build|config|pull|restart)
    docker compose -p "$PROJECT" "$cmd" "$@"
    ;;
  preflight)
    python3 scripts/preflight_check.py "$@"
    ;;
  *)
    echo "Usage: $0 {ps|logs|up|down|build|config|pull|restart|preflight} [args...]" >&2
    echo "All docker actions are scoped to -p $PROJECT" >&2
    exit 2
    ;;
esac
