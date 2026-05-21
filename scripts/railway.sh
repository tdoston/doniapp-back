#!/usr/bin/env bash
# Railway: build | release (pre-deploy, DB) | start (migrate + gunicorn)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

resolve_py() {
  for candidate in "$ROOT/.venv/bin/python" "/app/.venv/bin/python"; do
    if [ -x "$candidate" ]; then
      echo "$candidate"
      return
    fi
  done
  command -v python3 >/dev/null 2>&1 && echo python3 || echo python
}

PY="$(resolve_py)"
export DJANGO_DEBUG="${DJANGO_DEBUG:-0}"
CMD="${1:-}"

_has_db_url() {
  "$PY" -c "from swiftbookings.db_railway import resolve_database_url; import sys; sys.exit(0 if resolve_database_url() else 1)"
}

_log_db_target() {
  "$PY" -c "
from swiftbookings.db_railway import masked_db_target, resolve_database_url
print('[railway] DB', masked_db_target(resolve_database_url()), flush=True)
"
}

_await_db() {
  local n="${RAILWAY_DB_WAIT_ATTEMPTS:-24}"
  local i=1
  while [ "$i" -le "$n" ]; do
    if "$PY" manage.py check_db 2>/dev/null; then
      return 0
    fi
    echo "[railway] Postgres kutilyapti ($i/$n)..."
    sleep 5
    i=$((i + 1))
  done
  echo "[railway] XATO: Postgres ulanmadi"
  return 1
}

_db_release() {
  if ! _has_db_url; then
    echo "[railway] XATO: DATABASE_URL yoki POSTGRES_PRIVATE_URL yo'q"
    echo "  Railway: Postgres servisini doniapp-back ga Connect qiling"
    exit 1
  fi
  _log_db_target
  _await_db
  echo "[railway] bootstrap_postgres_schema"
  "$PY" manage.py bootstrap_postgres_schema
  echo "[railway] migrate"
  "$PY" manage.py migrate --noinput
  echo "[railway] seed_initial_db"
  "$PY" manage.py seed_initial_db
  echo "[railway] release OK"
}

case "$CMD" in
  build)
    echo "[railway] collectstatic (PY=$PY)"
    "$PY" manage.py collectstatic --noinput
    ;;
  release)
    _db_release
    ;;
  start)
    if _has_db_url; then
      _log_db_target
      echo "[railway] migrate (start)"
      "$PY" manage.py migrate --noinput
    else
      echo "[railway] ogohlantirish: DB URL yo'q"
    fi
    if [ ! -d staticfiles ] || [ -z "$(ls -A staticfiles 2>/dev/null || true)" ]; then
      "$PY" manage.py collectstatic --noinput
    fi
    PORT="${PORT:-8080}"
    echo "[railway] gunicorn 0.0.0.0:${PORT}"
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
