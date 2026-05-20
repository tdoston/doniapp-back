#!/usr/bin/env bash
# Railway: build | release (to'liq DB) | start (bootstrap skip + migrate + gunicorn)
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

_has_db_url() {
  "$PY" -c "from swiftbookings.db_railway import resolve_database_url; import sys; sys.exit(0 if resolve_database_url() else 1)"
}

_log_db_target() {
  if _has_db_url; then
    "$PY" -c "
from swiftbookings.db_railway import masked_db_target, resolve_database_url
print('[railway] DB', masked_db_target(resolve_database_url()))
"
  else
    echo "[railway] DB MISSING — Postgres → doniapp-back Connect (DATABASE_URL yoki POSTGRES_PRIVATE_URL)"
  fi
}

_await_db() {
  local n="${RAILWAY_DB_WAIT_ATTEMPTS:-12}"
  local i=1
  while [ "$i" -le "$n" ]; do
    if "$PY" manage.py check_db 2>/dev/null; then
      return 0
    fi
    echo "[railway] DB kutilyapti ($i/$n)..."
    sleep 10
    i=$((i + 1))
  done
  echo "[railway] XATO: Postgres javob bermadi — Railway Postgres servisini Restart qiling"
  return 1
}

_db_setup() {
  if ! _has_db_url; then
    echo "[railway] XATO: Postgres URL yo'q (DATABASE_URL / POSTGRES_PRIVATE_URL)"
    exit 1
  fi
  _log_db_target
  _await_db || exit 1
  echo "[railway] bootstrap_postgres_schema"
  "$PY" manage.py bootstrap_postgres_schema
  echo "[railway] migrate"
  "$PY" manage.py migrate --noinput
  echo "[railway] seed_initial_db"
  "$PY" manage.py seed_initial_db
}

case "$CMD" in
  build)
    echo "[railway] collectstatic"
    "$PY" manage.py collectstatic --noinput
    ;;
  release)
    _db_setup
    ;;
  start)
    if _has_db_url; then
      _log_db_target
      _await_db || exit 1
      echo "[railway] bootstrap (skip if ready)"
      "$PY" manage.py bootstrap_postgres_schema
      echo "[railway] migrate"
      "$PY" manage.py migrate --noinput
      echo "[railway] seed_initial_db"
      "$PY" manage.py seed_initial_db
    else
      echo "[railway] XATO: Postgres URL yo'q — Postgres → doniapp-back Connect"
      exit 1
    fi
    if [ ! -d staticfiles ] || [ -z "$(ls -A staticfiles 2>/dev/null || true)" ]; then
      echo "[railway] collectstatic (fallback)"
      "$PY" manage.py collectstatic --noinput
    fi
    PORT="${PORT:-8080}"
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
