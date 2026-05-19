#!/usr/bin/env bash
# Railway start: DB (private network) + gunicorn. Buildda postgres.railway.internal DNS ishlamaydi.
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

if [ -z "${DATABASE_URL:-}" ]; then
  echo "[railway-start] XATO: DATABASE_URL yo'q — Postgres pluginni backend servisiga ulang."
  exit 1
fi

echo "[railway-start] 1/5 bootstrap_postgres_schema..."
"$PY" manage.py bootstrap_postgres_schema

echo "[railway-start] 2/5 migrate..."
"$PY" manage.py migrate --noinput

echo "[railway-start] 3/5 seed_initial_db..."
"$PY" manage.py seed_initial_db

if [ ! -d staticfiles ] || [ -z "$(ls -A staticfiles 2>/dev/null || true)" ]; then
  echo "[railway-start] 4/5 collectstatic (staticfiles yo'q)..."
  "$PY" manage.py collectstatic --noinput
else
  echo "[railway-start] 4/5 collectstatic — builddan mavjud, o'tkazildi."
fi

echo "[railway-start] 5/5 gunicorn :$PORT"
exec "$PY" -m gunicorn swiftbookings.wsgi:application \
  --bind "0.0.0.0:${PORT}" \
  --workers 2 \
  --threads 4 \
  --timeout 120
