#!/usr/bin/env bash
# Lokal Homebrew Postgres: biznes jadvallarini yaratadi (migrate dan oldin).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PATH="/opt/homebrew/opt/postgresql@16/bin:${PATH}"
export PGHOST="${PGHOST:-127.0.0.1}"
export PGPORT="${PGPORT:-5432}"
export PGUSER="${POSTGRES_USER:-postgres}"
export PGPASSWORD="${POSTGRES_PASSWORD:-postgres}"
export PGDATABASE="${POSTGRES_DB:-swift_bookings}"
psql -v ON_ERROR_STOP=1 -f "$ROOT/sql/postgres_bootstrap.sql"
