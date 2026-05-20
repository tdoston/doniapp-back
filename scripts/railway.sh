#!/usr/bin/env bash
# Prod start = lokal `db:reset` oqimi (dropdb siz): bootstrap → migrate → seed → gunicorn
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

resolve_py() {
  # Railpack: /app/.venv/bin/python
  for candidate in "$ROOT/.venv/bin/python" "/app/.venv/bin/python"; do
    if [ -x "$candidate" ]; then
      echo "$candidate"
      return
    fi
  done
  if command -v python3 >/dev/null 2>&1; then
    echo "python3"
  else
    echo "python"
  fi
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
u = resolve_database_url()
print('[railway] DB', masked_db_target(u) if u else 'MISSING', flush=True)
"
}

_await_db() {
  local n="${RAILWAY_DB_WAIT_ATTEMPTS:-12}"
  local i=1
  while [ "$i" -le "$n" ]; do
    if "$PY" manage.py check_db 2>/dev/null; then
      return 0
    fi
    echo "[railway] Postgres kutilyapti ($i/$n)..."
    sleep 5
    i=$((i + 1))
  done
  echo "[railway] XATO: Postgres ulanmadi — Railway Postgres Restart + Redeploy"
  return 1
}

# Lokal `reset_local_db.sh` bilan bir xil (faqat dropdb yo'q)
_db_setup_local_flow() {
  if ! _has_db_url; then
    echo "[railway] XATO: DATABASE_URL / POSTGRES_PRIVATE_URL yo'q"
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
}

case "$CMD" in
  build)
    echo "[railway] collectstatic"
    "$PY" manage.py collectstatic --noinput
    ;;
  start)
    _db_setup_local_flow
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
    echo "usage: $0 build|start" >&2
    exit 1
    ;;
esac
