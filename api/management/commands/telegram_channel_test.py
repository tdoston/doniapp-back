"""Kanalga test xabar yuboradi: TELEGRAM_BOT_TOKEN + TELEGRAM_NOTIFY_CHAT_ID."""

from __future__ import annotations

import os

from django.core.management.base import BaseCommand, CommandError

from api.views import _telegram_notify_chat_id, _telegram_send_channel_html


class Command(BaseCommand):
    help = "Telegram kanalga test xabar (sendMessage). TELEGRAM_NOTIFY_CHAT_ID kerak."

    def handle(self, *args, **options):
        token = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
        if not token:
            raise CommandError("TELEGRAM_BOT_TOKEN yo'q.")
        chat = _telegram_notify_chat_id()
        if not chat:
            raise CommandError(
                "Kanal chat_id yo'q. Quyidagilardan bittasini .env ga qo'ying: "
                "TELEGRAM_NOTIFY_CHAT_ID, TELEGRAM_CHANNEL_CHAT_ID, TELEGRAM_CHANNEL_ID "
                "yoki lokal uchun TELEGRAM_CHANNEL_ID_TEST.\n"
                "Qiymat: @my_channel yoki -100…\n"
                "Bot kanalda admin bo'lib, post qilish huquqi bo'lishi kerak."
            )
        _telegram_send_channel_html(
            "<b>Swift Bookings — test</b>\n"
            "Kanal bildirishnomalari ishlayapti ✅\n"
            f"<code>chat_id={chat}</code>"
        )
        self.stdout.write(self.style.SUCCESS("Xabar yuborildi (xatolik bo'lsa server logida ERROR)."))
