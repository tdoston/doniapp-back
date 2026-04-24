"""API uchun DB ulanish xatolarini aniq JSON javobga aylantirish."""

from __future__ import annotations

from django.db.utils import OperationalError
from django.http import JsonResponse


class DatabaseUnavailableMiddleware:
    """`OperationalError` — odatda Postgres ulanishi / SSL / host."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        return self.get_response(request)

    def process_exception(self, request, exception):
        if not isinstance(exception, OperationalError):
            return None
        path = getattr(request, "path", "") or ""
        if not path.startswith("/api/"):
            return None
        return JsonResponse(
            {
                "error": "Ma'lumotlar bazasiga ulanib bo'lmadi.",
                "code": "db_unavailable",
            },
            status=503,
        )
