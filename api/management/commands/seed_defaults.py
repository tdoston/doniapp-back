"""Seed rooms/hostels and create superuser if env vars are set (idempotent)."""
import os

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Run seed_initial_db and create superuser from env vars."

    def handle(self, *args, **options):
        call_command("seed_initial_db", verbosity=0)
        self.stdout.write(self.style.SUCCESS("✓ seed_initial_db"))

        username = os.environ.get("DJANGO_SUPERUSER_USERNAME") or os.environ.get("DJANGO_ADMIN_USERNAME")
        password = os.environ.get("DJANGO_SUPERUSER_PASSWORD") or os.environ.get("DJANGO_ADMIN_PASSWORD")
        email = os.environ.get("DJANGO_SUPERUSER_EMAIL") or os.environ.get("DJANGO_ADMIN_EMAIL", "admin@localhost")

        if not password:
            self.stdout.write(self.style.WARNING("DJANGO_SUPERUSER_PASSWORD not set — skipping superuser."))
            return

        User = get_user_model()
        if User.objects.filter(is_superuser=True).exists():
            self.stdout.write(self.style.SUCCESS("✓ superuser already exists"))
            return

        User.objects.create_superuser(username=username or "admin", email=email, password=password)
        self.stdout.write(self.style.SUCCESS(f"✓ superuser created: {username or 'admin'}"))
