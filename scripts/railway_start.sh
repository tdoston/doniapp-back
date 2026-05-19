#!/usr/bin/env bash
# Railway start: migrate (idempotent) + gunicorn. Og'ir ish buildda (railway_build.sh).
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
PORT="${PORT:-8080}"

echo "[railway-start] migrate..."
"$PY" manage.py migrate --noinput

if [ ! -d staticfiles ] || [ -z "$(ls -A staticfiles 2>/dev/null || true)" ]; then
  echo "[railway-start] collectstatic (staticfiles yo'q)..."
  "$PY" manage.py collectstatic --noinput
fi

echo "[railway-start] gunicorn :$PORT"
exec "$PY" -m gunicorn swiftbookings.wsgi:application \
  --bind "0.0.0.0:${PORT}" \
  --workers 2 \
  --threads 4 \
  --timeout 120
