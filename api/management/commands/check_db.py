"""PostgreSQL ulanishini tekshirish (Railway Run command)."""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import connection

from swiftbookings.db_railway import masked_db_target, resolve_database_url


class Command(BaseCommand):
    help = "DATABASE_URL va SELECT 1 — Railway troubleshoot."

    def handle(self, *args, **options):
        url = resolve_database_url()
        if not url:
            self.stderr.write(self.style.ERROR("DATABASE_URL topilmadi"))
            return
        self.stdout.write(f"target: {masked_db_target(url)}")
        with connection.cursor() as c:
            c.execute("SELECT version()")
            ver = c.fetchone()[0]
        self.stdout.write(self.style.SUCCESS(f"OK — {ver[:80]}"))
