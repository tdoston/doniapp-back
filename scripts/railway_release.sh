#!/usr/bin/env bash
# Railway release: DB ishlar (private network). Start tez bo‘lishi uchun shu yerda.
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

if [ -z "${DATABASE_URL:-}" ]; then
  echo "[railway-release] XATO: DATABASE_URL yo'q."
  exit 1
fi

echo "[railway-release] 1/3 bootstrap_postgres_schema..."
"$PY" manage.py bootstrap_postgres_schema

echo "[railway-release] 2/3 migrate..."
"$PY" manage.py migrate --noinput

echo "[railway-release] 3/3 seed_initial_db..."
"$PY" manage.py seed_initial_db

echo "[railway-release] Tayyor."
