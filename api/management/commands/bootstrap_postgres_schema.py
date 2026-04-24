"""`sql/postgres_bootstrap.sql` — managed=False jadvallar; build ishonchsiz bo'lsa startda ham."""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection, transaction


class Command(BaseCommand):
    help = "PostgreSQL: biznes DDL (IF NOT EXISTS). Railway buildda psql o'tmasa ham konteyner startida tuzatadi."

    def handle(self, *args, **options):
        if settings.DATABASES["default"]["ENGINE"] != "django.db.backends.postgresql":
            self.stdout.write("bootstrap_postgres_schema: not PostgreSQL, skip.")
            return

        path = Path(settings.BASE_DIR) / "sql" / "postgres_bootstrap.sql"
        raw = path.read_text(encoding="utf-8")
        # BEGIN/COMMIT o'rniga bitta atomic blok
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

        with transaction.atomic():
            with connection.cursor() as cursor:
                for stmt in statements:
                    cursor.execute(stmt)

        self.stdout.write(self.style.SUCCESS("bootstrap_postgres_schema: OK"))
