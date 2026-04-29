"""Run seed_initial_db + ensure_admin in one step (idempotent)."""
import os

from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Seed rooms/hostels and create default superuser if env vars are set."

    def handle(self, *args, **options):
        self.stdout.write("→ seed_initial_db ...")
        call_command("seed_initial_db", verbosity=0)
        self.stdout.write(self.style.SUCCESS("✓ seed_initial_db done"))

        if os.environ.get("DJANGO_ADMIN_PASSWORD"):
            self.stdout.write("→ ensure_admin ...")
            call_command("ensure_admin", verbosity=0)
            self.stdout.write(self.style.SUCCESS("✓ ensure_admin done"))
        else:
            self.stdout.write(
                self.style.WARNING("DJANGO_ADMIN_PASSWORD not set — skipping superuser creation.")
            )
