#!/usr/bin/env bash
# Railway start: avval gunicorn (healthcheck), DB fon jarayonida.
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

if [ -n "${DATABASE_URL:-}" ]; then
  (
    echo "[railway-bg] bootstrap..."
    "$PY" manage.py bootstrap_postgres_schema
    echo "[railway-bg] migrate..."
    "$PY" manage.py migrate --noinput
    echo "[railway-bg] seed..."
    "$PY" manage.py seed_initial_db
    echo "[railway-bg] done."
  ) >> /tmp/railway-db-setup.log 2>&1 &
else
  echo "[railway-start] ogohlantirish: DATABASE_URL yo'q, DB setup o'tkazildi."
fi

if [ ! -d staticfiles ] || [ -z "$(ls -A staticfiles 2>/dev/null || true)" ]; then
  "$PY" manage.py collectstatic --noinput
fi

echo "[railway-start] gunicorn :$PORT"
exec "$PY" -m gunicorn swiftbookings.wsgi:application \
  --bind "0.0.0.0:${PORT}" \
  --workers 2 \
  --threads 4 \
  --timeout 120
