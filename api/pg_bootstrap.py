"""PostgreSQL: `sql/postgres_bootstrap.sql` — managed=False jadvallar (migrate va start uchun)."""

from __future__ import annotations

from pathlib import Path

from django.conf import settings


def postgres_business_schema_ready(connection) -> bool:
    """`hostels` jadvali bor — bootstrap qayta ishga shart emas."""
    if connection.vendor != "postgresql":
        return True
    with connection.cursor() as cursor:
        cursor.execute(
            """
            SELECT EXISTS (
              SELECT 1 FROM information_schema.tables
              WHERE table_schema = 'public' AND table_name = 'hostels'
            )
            """
        )
        return bool(cursor.fetchone()[0])


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
