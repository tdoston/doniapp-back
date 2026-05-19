#!/usr/bin/env bash
# Railway build: faqat collectstatic (DB buildda mavjud emas — postgres.railway.internal faqat runtime).
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

echo "[railway-build] collectstatic..."
"$PY" manage.py collectstatic --noinput

echo "[railway-build] Tayyor (DB ishlar startda)."
