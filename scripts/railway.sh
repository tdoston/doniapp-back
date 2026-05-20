#!/usr/bin/env bash
# Railway: build (collectstatic) | start (gunicorn darhol, DB fon jarayonida)
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
print('[railway] DB', masked_db_target(resolve_database_url()), flush=True)
"
  else
    echo "[railway] DB MISSING — Postgres → doniapp-back Connect"
  fi
}

_db_setup_sync() {
  _log_db_target
  local n="${RAILWAY_DB_WAIT_ATTEMPTS:-18}"
  local i=1
  while [ "$i" -le "$n" ]; do
    if "$PY" manage.py check_db 2>/dev/null; then
      break
    fi
    echo "[railway-bg] DB kutilyapti ($i/$n)..." >&2
    if [ "$i" -eq "$n" ]; then
      echo "[railway-bg] XATO: Postgres javob bermadi" >&2
      return 1
    fi
    sleep 10
    i=$((i + 1))
  done
  echo "[railway-bg] bootstrap_postgres_schema" >&2
  "$PY" manage.py bootstrap_postgres_schema
  echo "[railway-bg] migrate" >&2
  "$PY" manage.py migrate --noinput
  echo "[railway-bg] seed_initial_db" >&2
  "$PY" manage.py seed_initial_db
  echo "[railway-bg] DB setup tayyor" >&2
}

_start_db_background() {
  if ! _has_db_url; then
    echo "[railway] ogohlantirish: Postgres URL yo'q — API DB siz ishlamaydi"
    return
  fi
  (
    _db_setup_sync
  ) >> /tmp/railway-db.log 2>&1 &
  echo "[railway] DB setup fon rejimida (/tmp/railway-db.log)"
}

case "$CMD" in
  build)
    echo "[railway] collectstatic"
    "$PY" manage.py collectstatic --noinput
    ;;
  release)
    _db_setup_sync
    ;;
  start)
    if [ ! -d staticfiles ] || [ -z "$(ls -A staticfiles 2>/dev/null || true)" ]; then
      echo "[railway] collectstatic (fallback)"
      "$PY" manage.py collectstatic --noinput
    fi
    _start_db_background
    PORT="${PORT:-8080}"
    echo "[railway] gunicorn :${PORT} (DB fon jarayonida)"
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
