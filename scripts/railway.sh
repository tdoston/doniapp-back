#!/usr/bin/env bash
# Railway: build (collectstatic) | release (DB) | start (gunicorn)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [ -x .venv/bin/python ]; then
  PY=".venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PY="python3"
else
  PY="python"
fi

export DJANGO_DEBUG="${DJANGO_DEBUG:-0}"
CMD="${1:-}"

case "$CMD" in
  build)
    echo "[railway] collectstatic"
    "$PY" manage.py collectstatic --noinput
    ;;
  release)
    if [ -z "${DATABASE_URL:-}" ]; then
      echo "[railway] DATABASE_URL required (Postgres plugin)"
      exit 1
    fi
    echo "[railway] bootstrap_postgres_schema"
    "$PY" manage.py bootstrap_postgres_schema
    echo "[railway] migrate"
    "$PY" manage.py migrate --noinput
    echo "[railway] seed_initial_db"
    "$PY" manage.py seed_initial_db
    ;;
  start)
    PORT="${PORT:-8080}"
    if [ ! -d staticfiles ] || [ -z "$(ls -A staticfiles 2>/dev/null || true)" ]; then
      echo "[railway] collectstatic (fallback)"
      "$PY" manage.py collectstatic --noinput
    fi
    echo "[railway] gunicorn :${PORT}"
    exec "$PY" -m gunicorn swiftbookings.wsgi:application \
      --bind "0.0.0.0:${PORT}" \
      --workers 1 \
      --threads 4 \
      --timeout 120 \
      --access-logfile - \
      --error-logfile -
    ;;
  *)
    echo "usage: $0 build|release|start" >&2
    exit 1
    ;;
esac
