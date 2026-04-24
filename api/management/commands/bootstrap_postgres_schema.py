"""`sql/postgres_bootstrap.sql` — managed=False jadvallar; build ishonchsiz bo'lsa startda ham."""

from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection, transaction

from api.pg_bootstrap import apply_postgres_bootstrap_sql


class Command(BaseCommand):
    help = "PostgreSQL: biznes DDL (IF NOT EXISTS). Railway buildda psql o'tmasa ham konteyner startida tuzatadi."

    def handle(self, *args, **options):
        if settings.DATABASES["default"]["ENGINE"] != "django.db.backends.postgresql":
            self.stdout.write("bootstrap_postgres_schema: not PostgreSQL, skip.")
            return

        with transaction.atomic():
            apply_postgres_bootstrap_sql(connection)

        self.stdout.write(self.style.SUCCESS("bootstrap_postgres_schema: OK"))
