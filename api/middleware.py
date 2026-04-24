"""API uchun DB xatolarini JSON javobga aylantirish (prod logda HTML 500 o'rniga)."""

from __future__ import annotations

from django.conf import settings
from django.db.utils import OperationalError, ProgrammingError
from django.http import JsonResponse


class DatabaseUnavailableMiddleware:
    """`OperationalError` — ulanish; `ProgrammingError` (does not exist) — migrate qilinmagan sxema."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        path = getattr(request, "path", "") or ""
        if not path.startswith("/api/"):
            return None

        if isinstance(exception, OperationalError):
            return JsonResponse(
                {
                    "error": "Ma'lumotlar bazasiga ulanib bo'lmadi.",
                    "code": "db_unavailable",
                },
                status=503,
            )

        if isinstance(exception, ProgrammingError):
            detail = str(exception).lower()
            if "does not exist" not in detail and "undefinedcolumn" not in detail:
                return None
            body: dict = {
                "error": "Ma'lumotlar bazasi sxemasi loyiha bilan mos emas. Avval `migrate`, keyin `seed_initial_db` (Railway Run command).",
                "code": "db_schema_mismatch",
            }
            if settings.DEBUG:
                body["detail"] = str(exception)
            return JsonResponse(body, status=503)

        return None
