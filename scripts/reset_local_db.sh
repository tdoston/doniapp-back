#!/usr/bin/env bash
# Lokal DB ni tozalab qayta yaratadi + bootstrap + migrate (faqat o'zingizning mashinangizda).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PATH="/opt/homebrew/opt/postgresql@16/bin:${PATH}"
export PGHOST="${PGHOST:-127.0.0.1}"
export PGPORT="${PGPORT:-5432}"
export PGUSER="${POSTGRES_USER:-postgres}"
export PGPASSWORD="${POSTGRES_PASSWORD:-postgres}"
DB="${POSTGRES_DB:-swift_bookings}"
dropdb -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" --if-exists "$DB" || true
createdb -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" "$DB"
export PGDATABASE="$DB"
psql -v ON_ERROR_STOP=1 -f "$ROOT/sql/postgres_bootstrap.sql"
cd "$ROOT"
exec "${PYTHON:-./.venv/bin/python}" manage.py migrate --noinput
