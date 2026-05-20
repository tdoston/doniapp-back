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

_log_db_target() {
  if [ -n "${DATABASE_URL:-}" ]; then
    "$PY" -c "
from swiftbookings.db_railway import masked_db_target, resolve_database_url
u = resolve_database_url()
print('[railway] DB', masked_db_target(u) if u else 'MISSING')
" 2>/dev/null || echo "[railway] DB (DATABASE_URL set)"
  else
    echo "[railway] DB MISSING — Postgres pluginni backend servisiga ulang"
  fi
}

_db_setup() {
  if [ -z "${DATABASE_URL:-}" ]; then
    echo "[railway] XATO: DATABASE_URL yo'q"
    exit 1
  fi
  _log_db_target
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
    if [ -n "${DATABASE_URL:-}" ]; then
      _log_db_target
      echo "[railway] bootstrap (skip if ready)"
      "$PY" manage.py bootstrap_postgres_schema
      echo "[railway] migrate"
      "$PY" manage.py migrate --noinput
    else
      echo "[railway] XATO: DATABASE_URL yo'q — Postgres → doniapp-back Connect"
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
