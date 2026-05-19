#!/usr/bin/env bash
# Railway build: DDL + migrate + seed + collectstatic (DATABASE_URL build vaqtida kerak).
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
  echo "[railway-build] XATO: DATABASE_URL yo'q — Postgres pluginni backend servisiga ulang."
  exit 1
fi

echo "[railway-build] DB → $(echo "$DATABASE_URL" | sed -E 's#(postgresql://[^:]+:)[^@]+#\1***#')"

echo "[railway-build] 1/4 bootstrap_postgres_schema (Django, psql shart emas)..."
"$PY" manage.py bootstrap_postgres_schema

echo "[railway-build] 2/4 migrate..."
"$PY" manage.py migrate --noinput

echo "[railway-build] 3/4 seed_initial_db..."
"$PY" manage.py seed_initial_db

echo "[railway-build] 4/4 collectstatic..."
"$PY" manage.py collectstatic --noinput

echo "[railway-build] Tayyor."
