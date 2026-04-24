"""`TELEGRAM_BOT_TOKEN` orqali Telegram `getMe` chaqiradi (token to'g'riligini tekshirish)."""

from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.request

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Telegram bot tokenni tekshiradi (getMe). Muhit: TELEGRAM_BOT_TOKEN"

    def handle(self, *args, **options):
        token = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
        if not token:
            raise CommandError(
                "TELEGRAM_BOT_TOKEN yo'q. Loyiha ildizida:\n"
                "  export TELEGRAM_BOT_TOKEN='<BotFather token>'\n"
                "  npm run telegram:verify\n"
                "Yoki: django_backend/.env faylida TELEGRAM_BOT_TOKEN=... (gitga qo'shmang)"
            )
        url = f"https://api.telegram.org/bot{token}/getMe"
        try:
            req = urllib.request.Request(url, method="GET")
            ctx = ssl.create_default_context()
            with urllib.request.urlopen(req, timeout=20, context=ctx) as resp:
                raw = json.loads(resp.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")[:800]
            raise CommandError(f"Telegram HTTP {e.code}: {body}") from e
        except Exception as e:
            raise CommandError(str(e)) from e
        if not raw.get("ok"):
            raise CommandError(json.dumps(raw, ensure_ascii=False))
        self.stdout.write(self.style.SUCCESS(json.dumps(raw["result"], indent=2, ensure_ascii=False)))
