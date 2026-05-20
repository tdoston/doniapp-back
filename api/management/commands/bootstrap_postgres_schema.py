"""`sql/postgres_bootstrap.sql` — managed=False jadvallar (faqat kerak bo'lsa)."""

from __future__ import annotations

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import connection

from api.pg_bootstrap import apply_postgres_bootstrap_sql, postgres_business_schema_ready


class Command(BaseCommand):
    help = "PostgreSQL biznes DDL (IF NOT EXISTS). Mavjud sxemada hech narsa qilmaydi."

    def handle(self, *args, **options):
        if settings.DATABASES["default"]["ENGINE"] != "django.db.backends.postgresql":
            self.stdout.write("bootstrap_postgres_schema: not PostgreSQL, skip.")
            return

        if postgres_business_schema_ready(connection):
            self.stdout.write("bootstrap_postgres_schema: already ready, skip.")
            return

        # DDL — alohida statementlar (uzun transaction lock qilmasin)
        apply_postgres_bootstrap_sql(connection)
        self.stdout.write(self.style.SUCCESS("bootstrap_postgres_schema: OK"))
