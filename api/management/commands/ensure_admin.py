"""Superuser yaratish. Parol: DJANGO_ADMIN_PASSWORD yoki DEBUG da 'admin'. --force: qayta yaratish."""

import os

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Superuser yaratadi. --force: mavjud superuserlarni o'chirib, yangisini yaratadi."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Barcha superuserlarni o'chiradi va yangi superuser yaratadi.",
        )

    def handle(self, *args, **options):
        User = get_user_model()
        force = options["force"]
        username = os.environ.get("DJANGO_ADMIN_USERNAME", "admin")
        email = os.environ.get("DJANGO_ADMIN_EMAIL", "admin@localhost")

        if force:
            n_su, _ = User.objects.filter(is_superuser=True).delete()
            n_u, _ = User.objects.filter(username=username).delete()
            if n_su or n_u:
                self.stdout.write(
                    self.style.WARNING(f"O'chirildi: superuserlar={n_su}, login={username!r} yozuvlari={n_u}.")
                )
        elif User.objects.filter(is_superuser=True).exists():
            self.stdout.write(self.style.SUCCESS("Superuser allaqachon mavjud. Qayta yaratish: --force"))
            return

        if User.objects.filter(username=username).exists():
            raise CommandError(
                f"'{username}' band. Boshqa DJANGO_ADMIN_USERNAME qo'ying yoki: python manage.py ensure_admin --force"
            )

        password = os.environ.get("DJANGO_ADMIN_PASSWORD")
        if not password:
            if settings.DEBUG:
                password = "admin"
                self.stdout.write(self.style.WARNING("DEBUG: parol 'admin' (DJANGO_ADMIN_PASSWORD o'rnatilmagan)."))
            else:
                raise CommandError("DJANGO_ADMIN_PASSWORD muhit o'zgaruvchisini o'rnating (DEBUG=0).")

        User.objects.create_superuser(username=username, email=email, password=password)
        self.stdout.write(self.style.SUCCESS(f"Superuser yaratildi: {username}"))
