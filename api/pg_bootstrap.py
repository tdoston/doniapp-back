"""PostgreSQL: `sql/postgres_bootstrap.sql` — managed=False jadvallar (migrate va start uchun)."""

from __future__ import annotations

from pathlib import Path

from django.conf import settings


def apply_postgres_bootstrap_sql(connection) -> None:
    """Bo'sh DB uchun biznes DDL; IF NOT EXISTS — takrorlash xavfsiz. Faqat PostgreSQL."""
    if connection.vendor != "postgresql":
        return

    path = Path(settings.BASE_DIR) / "sql" / "postgres_bootstrap.sql"
    raw = path.read_text(encoding="utf-8")
    body = raw.replace("BEGIN;", "").replace("COMMIT;", "")
    statements: list[str] = []
    for chunk in body.split(";"):
        stmt = chunk.strip()
        if not stmt:
            continue
        if not any(
            line.strip() and not line.strip().startswith("--")
            for line in stmt.splitlines()
        ):
            continue
        statements.append(stmt)

    with connection.cursor() as cursor:
        for stmt in statements:
            cursor.execute(stmt)
