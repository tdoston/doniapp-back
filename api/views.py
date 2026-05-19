from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import time
import uuid
from datetime import date
from typing import Any
from urllib import parse, request
from urllib.error import HTTPError, URLError

import bcrypt
from django.db import connection, transaction
from django.db.utils import IntegrityError
from django.http import JsonResponse
from django.core import signing
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .guest_identity import (
    compute_identity_key,
    ensure_guest_schema,
    guest_phone_column_value,
    identity_hostel_active_stay_overlap_detail,
    normalize_passport_series,
    normalize_phone_digits,
    resolve_guest_name_for_line,
    upsert_guest,
    upsert_guest_document_fields,
)
from .id_ocr import parse_document_fields_from_photo, parse_document_fields_from_photo_with_raw
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
LOGIN_RE = re.compile(r"^[a-z0-9._-]+$", re.I)
CLEANING_PHOTO_RETENTION_DAYS = 5
TELEGRAM_API_BASE = "https://api.telegram.org"
AUTH_TOKEN_SALT = "swift-bookings-auth-v1"
AUTH_TOKEN_MAX_AGE_SEC = 60 * 60 * 24 * 30

logger = logging.getLogger(__name__)


def _tg_html(s: str) -> str:
    return (
        (s or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _telegram_caption_html_trim(html: str, max_len: int = 1024) -> str:
    """Telegram photo/media caption — maks. 1024 belgi."""
    t = (html or "").strip()
    if len(t) <= max_len:
        return t
    return t[: max_len - 1] + "…"


_TG_NOTES_EMBEDDED_CONTACT = re.compile(
    r"^(Telefon|Pasport/guvohnoma|Hujjat):\s",
    re.I,
)


def _telegram_notes_without_embedded_contact(notes: str) -> str:
    """`formatNotesWithContactDetails` qo'shgan qatorlar — kanalda takror bo'lmasin (📞/🪪 allaqachon bor)."""
    lines_out: list[str] = []
    for line in (notes or "").split("\n"):
        t = line.strip()
        if not t:
            lines_out.append("")
            continue
        if _TG_NOTES_EMBEDDED_CONTACT.match(t):
            continue
        lines_out.append(line.rstrip())
    text = "\n".join(lines_out)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def _super_admin_tg_ids() -> set[int]:
    raw = str(os.environ.get("SUPER_ADMIN_TELEGRAM_IDS", "") or "").strip()
    out: set[int] = set()
    if not raw:
        return out
    for p in raw.split(","):
        s = p.strip()
        if not s:
            continue
        try:
            out.add(int(s))
        except ValueError:
            continue
    return out


def _ensure_users_auth_schema(cursor: Any) -> None:
    cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS telegram_user_id BIGINT")
    cursor.execute(
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS auth_provider VARCHAR(20) NOT NULL DEFAULT 'password'"
    )
    cursor.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS avatar_url TEXT")
    cursor.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_indexes
                WHERE schemaname = current_schema()
                  AND indexname = 'users_telegram_user_id_uq'
            ) THEN
                EXECUTE 'CREATE UNIQUE INDEX users_telegram_user_id_uq ON users (telegram_user_id) WHERE telegram_user_id IS NOT NULL';
            END IF;
        END $$;
        """
    )
    cursor.execute(
        """
        DO $$
        DECLARE c_name text;
        BEGIN
            SELECT conname INTO c_name
            FROM pg_constraint
            WHERE conrelid = 'users'::regclass
              AND contype = 'c'
              AND pg_get_constraintdef(oid) ILIKE '%%role%%';
            IF c_name IS NOT NULL THEN
                EXECUTE format('ALTER TABLE users DROP CONSTRAINT %I', c_name);
            END IF;
            ALTER TABLE users
              ADD CONSTRAINT users_role_check CHECK (role IN ('super_admin', 'admin', 'staff'));
        EXCEPTION WHEN duplicate_object THEN
            NULL;
        END $$;
        """
    )


def _telegram_post(token: str, method: str, payload: dict[str, Any], *, timeout_sec: float = 8.0) -> int | None:
    ok, _desc, mid = _telegram_api_request(token, method, payload, timeout_sec=timeout_sec)
    return mid if ok else None


def _telegram_api_request(
    token: str, method: str, payload: dict[str, Any], *, timeout_sec: float = 8.0
) -> tuple[bool, str, int | None]:
    """Telegram Bot API chaqiruvi. (muvaffaqiyat, tavsif yoki xato matni, message_id)."""
    if "parse_mode" not in payload and method in ("sendMessage", "sendPhoto"):
        payload = {**payload, "parse_mode": "HTML"}
    # JSON POST — uzun matn / UTF-8 uchun urlencoded qatoriga nisbatan ishonchliroq
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        f"{TELEGRAM_API_BASE}/bot{token}/{method}",
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout_sec) as resp:
            if resp.status < 200 or resp.status >= 300:
                return False, f"HTTP {resp.status}", None
            raw = resp.read().decode("utf-8")
    except HTTPError as e:
        try:
            err_body = e.read().decode("utf-8")
        except Exception:
            err_body = str(e)
        return False, err_body or str(e), None
    except (URLError, TimeoutError, OSError, ValueError) as e:
        return False, str(e), None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return False, "Invalid JSON from Telegram", None
    if not data.get("ok"):
        desc = str(data.get("description") or data.get("error_code") or data)
        return False, desc, None
    result = data.get("result") or {}
    mid = result.get("message_id")
    return True, "ok", int(mid) if mid is not None else None


def _telegram_notify_chat_id() -> str:
    """Kanal yoki guruh: @mychannel yoki -100… ID. Bir nechta env nomlari qo‘llab-quvvatlanadi."""
    for key in (
        "TELEGRAM_NOTIFY_CHAT_ID",
        "TELEGRAM_CHANNEL_CHAT_ID",
        "TELEGRAM_CHANNEL_ID",
        "TELEGRAM_CHANNEL_ID_TEST",
    ):
        v = str(os.environ.get(key, "") or "").strip()
        if v:
            return v
    return ""


_channel_id_missing_logged = False


def _telegram_send_channel_html(text: str) -> int | None:
    """Kanalga matn. Muvaffaqiyatda `message_id`, aks holda None."""
    global _channel_id_missing_logged
    token = str(os.environ.get("TELEGRAM_BOT_TOKEN", "") or "").strip()
    chat_id = _telegram_notify_chat_id()
    if not token:
        return None
    if not chat_id:
        if not _channel_id_missing_logged:
            logger.warning(
                "Telegram kanal: TELEGRAM_NOTIFY_CHAT_ID / TELEGRAM_CHANNEL_CHAT_ID / "
                "TELEGRAM_CHANNEL_ID (yoki lokalda TELEGRAM_CHANNEL_ID_TEST) "
                "o'rnatilmagan — kanalga xabar yuborilmaydi. .env tekshiring."
            )
            _channel_id_missing_logged = True
        return None
    t = (text or "").strip()
    if not t:
        return None
    if len(t) > 4000:
        t = t[:3997] + "…"
    ok, desc, mid = _telegram_api_request(
        token,
        "sendMessage",
        {
            "chat_id": chat_id,
            "text": t,
            "disable_web_page_preview": True,
        },
    )
    if not ok:
        logger.error("Telegram kanalga yuborib bo'lmadi: %s", desc)
        return None
    return mid


def _telegram_send_channel_html_reply(reply_to_message_id: int, text: str) -> int | None:
    """Asl kanal postiga reply (patch diff)."""
    ctx = _telegram_channel_ready()
    if not ctx or reply_to_message_id <= 0:
        return None
    token, chat_id = ctx
    t = (text or "").strip()
    if not t:
        return None
    if len(t) > 4000:
        t = t[:3997] + "…"
    ok, desc, mid = _telegram_api_request(
        token,
        "sendMessage",
        {
            "chat_id": chat_id,
            "text": t,
            "reply_to_message_id": int(reply_to_message_id),
            "disable_web_page_preview": True,
        },
    )
    if not ok:
        logger.error("Telegram kanal reply yuborib bo'lmadi: %s", desc)
        return None
    return mid


def _telegram_channel_ready() -> tuple[str, str] | None:
    token = str(os.environ.get("TELEGRAM_BOT_TOKEN", "") or "").strip()
    chat_id = _telegram_notify_chat_id()
    if not token or not chat_id:
        return None
    return token, chat_id


def _mime_to_image_ext(mime: str) -> str:
    m = (mime or "").lower()
    if "png" in m:
        return "png"
    if "webp" in m:
        return "webp"
    if "gif" in m:
        return "gif"
    return "jpg"


def _fetch_image_url(url: str, *, max_bytes: int = 10 * 1024 * 1024) -> tuple[bytes, str] | None:
    if not url.startswith(("http://", "https://")):
        return None
    try:
        req = request.Request(url, headers={"User-Agent": "SwiftBookings/1"})
        with request.urlopen(req, timeout=25) as resp:
            ctype = (resp.headers.get("Content-Type") or "application/octet-stream").split(";")[0].strip()
            data = resp.read(max_bytes + 1)
            if len(data) > max_bytes:
                return None
            return data, ctype or "image/jpeg"
    except (HTTPError, URLError, TimeoutError, OSError, ValueError):
        return None


def _parse_booking_image_payload(raw: str) -> tuple[bytes, str] | None:
    """data: URL (base64) yoki ochiq HTTP(S) rasm."""
    s = (raw or "").strip()
    if not s:
        return None
    if s.startswith("data:"):
        try:
            head, b64part = s.split(",", 1)
            mime = "image/jpeg"
            meta = head[5:].split(";")[0].strip()
            if meta:
                mime = meta
            raw_bytes = base64.b64decode(b64part, validate=False)
            if not raw_bytes:
                return None
            return raw_bytes, mime
        except (ValueError, TypeError, base64.binascii.Error):
            return None
    return _fetch_image_url(s)


def _telegram_multipart_request(
    token: str,
    method: str,
    string_fields: dict[str, str],
    file_fields: list[tuple[str, str, bytes, str]],
    *,
    timeout_sec: float = 90.0,
) -> tuple[bool, str, int | None]:
    boundary = f"----SwiftBk{uuid.uuid4().hex}"
    crlf = b"\r\n"
    parts: list[bytes] = []
    for k, v in string_fields.items():
        parts.append(f"--{boundary}".encode("ascii") + crlf)
        parts.append(f'Content-Disposition: form-data; name="{k}"'.encode("ascii") + crlf + crlf)
        parts.append(v.encode("utf-8") + crlf)
    for field_name, filename, content, ctype in file_fields:
        parts.append(f"--{boundary}".encode("ascii") + crlf)
        cd = f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"'
        parts.append(cd.encode("utf-8") + crlf)
        parts.append(f"Content-Type: {ctype}".encode("ascii") + crlf + crlf)
        parts.append(content + crlf)
    parts.append(f"--{boundary}--".encode("ascii") + crlf)
    body = b"".join(parts)
    req = request.Request(
        f"{TELEGRAM_API_BASE}/bot{token}/{method}",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout_sec) as resp:
            if resp.status < 200 or resp.status >= 300:
                return False, f"HTTP {resp.status}", None
            raw = resp.read().decode("utf-8")
    except HTTPError as e:
        try:
            err_body = e.read().decode("utf-8")
        except Exception:
            err_body = str(e)
        return False, err_body or str(e), None
    except (URLError, TimeoutError, OSError, ValueError) as e:
        return False, str(e), None
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return False, "Invalid JSON from Telegram", None
    if not data.get("ok"):
        desc = str(data.get("description") or data.get("error_code") or data)
        return False, desc, None
    result = data.get("result")
    if isinstance(result, list) and result:
        mid = (result[0] or {}).get("message_id") if isinstance(result[0], dict) else None
        return True, "ok", int(mid) if mid is not None else None
    if isinstance(result, dict):
        mid = result.get("message_id")
        return True, "ok", int(mid) if mid is not None else None
    return True, "ok", None


def _telegram_send_channel_booking_images(caption_html: str, urls: list[str]) -> tuple[bool, int | None]:
    """Bitta sendPhoto yoki sendMediaGroup (maks. 3 rasm). Qaytadi: (ok, message_id — reply uchun birinchi post)."""
    ctx = _telegram_channel_ready()
    if not ctx or not urls:
        return False, None
    token, chat_id = ctx
    blobs: list[tuple[bytes, str]] = []
    for u in urls[:3]:
        got = _parse_booking_image_payload(str(u))
        if got:
            blobs.append(got)
    if not blobs:
        logger.warning("Telegram kanal: hujjat rasmlari decode qilinmadi (data URL / HTTPS tekshiring)")
        return False, None
    cap = _telegram_caption_html_trim(caption_html)
    chunk = blobs[:3]

    if len(chunk) == 1:
        b, mime = chunk[0]
        ext = _mime_to_image_ext(mime)
        fields: dict[str, str] = {
            "chat_id": chat_id,
            "caption": cap,
            "parse_mode": "HTML",
        }
        ok, desc, mid = _telegram_multipart_request(
            token,
            "sendPhoto",
            fields,
            [("photo", f"doc.{ext}", b, mime or "image/jpeg")],
        )
        if not ok:
            logger.error("Telegram kanal sendPhoto: %s", desc)
            return False, None
        return True, mid

    media: list[dict[str, Any]] = []
    file_fields: list[tuple[str, str, bytes, str]] = []
    for j, (b, mime) in enumerate(chunk):
        attach = f"f{j}"
        ext = _mime_to_image_ext(mime)
        item: dict[str, Any] = {"type": "photo", "media": f"attach://{attach}"}
        if j == 0:
            item["caption"] = cap
            item["parse_mode"] = "HTML"
        media.append(item)
        file_fields.append((attach, f"p{j}.{ext}", b, mime or "image/jpeg"))
    ok, desc, mid = _telegram_multipart_request(
        token,
        "sendMediaGroup",
        {"chat_id": chat_id, "media": json.dumps(media)},
        file_fields,
    )
    if not ok:
        logger.error("Telegram kanal sendMediaGroup: %s", desc)
        return False, None
    return True, mid


def _room_display_label(hostel_name: str, room_code: str) -> str:
    with connection.cursor() as c:
        c.execute(
            """
            SELECT COALESCE(r.name, r.code, '')
            FROM rooms r
            JOIN hostels h ON h.id = r.hostel_id
            WHERE h.name = %s AND r.code = %s
            LIMIT 1
            """,
            [hostel_name, room_code],
        )
        row = c.fetchone()
    if row and str(row[0] or "").strip():
        return str(row[0]).strip()
    return room_code


def _money_uz_spaced(val: Any) -> str:
    """76000 → \"76 000\" (mingliklar orasida bo'shliq)."""
    s = _money_int_text(val)
    try:
        n = int(s)
    except ValueError:
        n = 0
    return f"{n:,}".replace(",", " ")


def _booking_channel_display_id(check_in_date: str, booking_uuid: str) -> str:
    """Kanal xabari: YYMMDD-qisqa (masalan: 260507-92923)."""
    d = (check_in_date or "").strip()[:10]
    prefix = "000000"
    if len(d) == 10 and d[4] == "-" and d[7] == "-":
        try:
            y, m, dd = (int(d[0:4]), int(d[5:7]), int(d[8:10]))
            prefix = f"{y % 100:02d}{m:02d}{dd:02d}"
        except ValueError:
            pass
    uid = booking_uuid or ""
    digits = "".join(ch for ch in uid if ch.isdigit())
    if len(digits) >= 5:
        tail = digits[-5:]
    else:
        h = "".join(ch for ch in uid if ch.isalnum()).lower()
        tail = h[-5:] if len(h) >= 5 else (h or "00000")
    return f"{prefix}-{tail}"


def _notify_channel_room_place_line(hostel: str, room_code: str) -> str:
    label = _room_display_label(hostel, room_code)
    rc = (room_code or "").strip()
    if not label or label == rc:
        return f"{_tg_html(hostel)} · {_tg_html(rc)}"
    return f"{_tg_html(hostel)} · {_tg_html(label)} · {_tg_html(rc)}"


def _ensure_bed_bookings_telegram_channel_message_id_column(cursor: Any) -> None:
    cursor.execute(
        """
        SELECT 1
        FROM information_schema.columns
        WHERE table_schema = 'public'
          AND table_name = 'bed_bookings'
          AND column_name = 'telegram_channel_message_id'
        LIMIT 1
        """
    )
    if cursor.fetchone():
        return
    cursor.execute(
        "ALTER TABLE bed_bookings ADD COLUMN telegram_channel_message_id BIGINT NULL"
    )


def _booking_photos_sig(raw: str) -> str:
    try:
        j = json.loads(raw or "[]")
        if isinstance(j, list):
            return json.dumps([str(x) for x in j if isinstance(x, str)], ensure_ascii=False)
    except (json.JSONDecodeError, TypeError, ValueError):
        pass
    return raw or ""


def _booking_telegram_snapshot_row(
    check_in_date: Any,
    nights: Any,
    guest_name: Any,
    guest_phone: Any,
    price: Any,
    paid: Any,
    notes: Any,
    photos: Any,
    checked_in_by: Any,
    booking_kind_raw: Any,
) -> dict[str, Any]:
    try:
        ni = int(nights)
    except (TypeError, ValueError):
        ni = 1
    if ni < 1:
        ni = 1
    return {
        "check_in_date": str(check_in_date or "")[:10],
        "nights": ni,
        "guest_name": str(guest_name or ""),
        "guest_phone": str(guest_phone or ""),
        "price": int(_money_int_text(price)),
        "paid": int(_money_int_text(paid)),
        "notes": _telegram_notes_without_embedded_contact(str(notes or "")),
        "photos": _booking_photos_sig(str(photos or "[]")),
        "checked_in_by": str(checked_in_by or ""),
        "booking_kind": str(booking_kind_raw or "check_in").strip().lower(),
    }


def _booking_channel_patch_reply_html(
    before: dict[str, Any],
    after: dict[str, Any],
    booking_uuid: str,
    who_line_html: str,
) -> str:
    """Kanal postiga reply uchun o'zgarishlar matni (HTML). Bo'sh — yuborilmasin."""
    lines: list[str] = []
    cid = _booking_channel_display_id(str(after.get("check_in_date") or ""), booking_uuid)

    if str(before.get("check_in_date")) != str(after.get("check_in_date")):
        lines.append(
            f"• 📅 Sana: {_tg_html(str(before['check_in_date']))} → {_tg_html(str(after['check_in_date']))}"
        )
    if int(before.get("nights") or 1) != int(after.get("nights") or 1):
        lines.append(
            f"• 🌙 Tunlar: {int(before.get('nights') or 1)} → <b>{int(after.get('nights') or 1)} tun</b>"
        )

    nb, na = int(before.get("nights") or 1), int(after.get("nights") or 1)
    pb, pa = int(before.get("price") or 0), int(after.get("price") or 0)
    payb, paya = int(before.get("paid") or 0), int(after.get("paid") or 0)
    debt_b = max(0, pb * nb - payb)
    debt_a = max(0, pa * na - paya)
    money_changed = pb != pa or payb != paya or nb != na
    if money_changed:
        lines.append(
            f"• 💰 Narx: {_money_uz_spaced(pb)} → {_money_uz_spaced(pa)} so'm"
        )
        lines.append(
            f"• 💳 To'langan: {_money_uz_spaced(payb)} → {_money_uz_spaced(paya)} so'm"
        )
        lines.append(
            f"• 📉 Qarz: {_money_uz_spaced(debt_b)} → {_money_uz_spaced(debt_a)} so'm"
        )
        if debt_a == 0 and debt_b > 0:
            lines.append("✅ <b>To'liq to'langan</b>")

    if str(before.get("guest_name") or "") != str(after.get("guest_name") or ""):
        lines.append(
            f"• 👤 Mehmon: {_tg_html(str(before.get('guest_name') or '—'))} → "
            f"{_tg_html(str(after.get('guest_name') or '—'))}"
        )

    gpb, gpa = str(before.get("guest_phone") or ""), str(after.get("guest_phone") or "")
    if gpb != gpa:
        b_disp = _tg_html(format_guest_contact(gpb) or gpb[:40] or "—")
        a_disp = _tg_html(format_guest_contact(gpa) or gpa[:40] or "—")
        lines.append(f"• 📞 Telefon: {b_disp} → {a_disp}")

    notes_b = str(before.get("notes") or "")
    notes_a = str(after.get("notes") or "")
    if notes_b != notes_a:

        def _trunc_note(s: str, n: int = 100) -> str:
            s = (s or "").strip()
            return s if len(s) <= n else s[: n - 1] + "…"

        lines.append(
            f"• 📝 Izoh: {_tg_html(_trunc_note(notes_b))} → {_tg_html(_trunc_note(notes_a))}"
        )

    if str(before.get("photos") or "") != str(after.get("photos") or ""):
        lines.append("• 🖼 Hujjat rasmlari yangilandi")

    kb, ka = str(before.get("booking_kind") or "check_in"), str(after.get("booking_kind") or "check_in")
    if kb != ka:
        if kb == "bron" and ka == "check_in":
            lines.append("• Tur: 🟠 Bron → 🟢 Check-in")
        else:
            lines.append(f"• Tur: {_tg_html(kb)} → {_tg_html(ka)}")

    cb, ca = str(before.get("checked_in_by") or ""), str(after.get("checked_in_by") or "")
    if cb != ca:
        lines.append(
            f"• 👨‍💼 Administrator: {_tg_html(cb or '—')} → {_tg_html(ca or '—')}"
        )

    if not lines:
        return ""

    header = f"🔄 <b>Yangilanish</b> 🆔 <code>{_tg_html(cid)}</code>"
    parts = [header, *lines]
    if who_line_html:
        parts.append(who_line_html)
    return "\n".join(parts)


def _notify_booking_channel_after_create(
    *,
    hostel: str,
    room_code: str,
    check_in_date: str,
    nights: int,
    checked_in_by: str,
    lines: list[dict[str, Any]],
    inserted_ids: list[str],
    resolved_lines: list[tuple[str | None, str, str, str | None]],
) -> None:
    if len(inserted_ids) != len(lines) or len(resolved_lines) != len(lines):
        return
    with connection.cursor() as _c0:
        _ensure_bed_bookings_telegram_channel_message_id_column(_c0)
    for line, bid, triple in zip(lines, inserted_ids, resolved_lines):
        _ik, phone_raw, passport_raw, convert_booking_id = triple
        raw_kind = str(line.get("bookingKind") or line.get("booking_kind") or "check_in").lower()
        is_bron = raw_kind == "bron"
        ln = line.get("nights")
        line_nights = int(ln) if isinstance(ln, int) and 1 <= ln <= 365 else nights
        guest_name_raw = str(line.get("guestName") or "").strip()
        guest_line = _tg_html(guest_name_raw) if guest_name_raw else "—"

        if is_bron:
            title = "🟠 Bron"
        else:
            title = "🟢 Check-in"

        loc = _notify_channel_room_place_line(hostel, room_code)
        date_line = f"📅 {_tg_html(check_in_date)} · <b>{line_nights} tun</b>"

        p = int(_money_int_text(line.get("price", "")))
        pd_amt = int(_money_int_text(line.get("paid", "")))
        debt = max(0, p * line_nights - pd_amt)
        narx = _money_uz_spaced(p)
        tolangan = _money_uz_spaced(pd_amt)
        qarz = _money_uz_spaced(debt)

        compact_id = _booking_channel_display_id(check_in_date, bid)

        pnd = normalize_phone_digits(phone_raw)
        tel_disp = _tg_html(format_phone(pnd)) if pnd else "—"

        ps = normalize_passport_series(passport_raw)
        pass_disp = _tg_html(ps) if ps else "—"

        adm = (checked_in_by or "").strip()
        admin_disp = _tg_html(adm) if adm else "—"

        notes = _telegram_notes_without_embedded_contact(str(line.get("notes") or ""))
        izoh_disp = _tg_html(notes) if notes else "—"

        header_lines = [
            title,
            f"👤 {guest_line}",
            f"📍 {loc}",
            date_line,
            "",
            "💰 Pul",
            f"   Narx: {narx} so'm",
            f"   To'langan: {tolangan} so'm",
            f"   Qarz: {qarz} so'm",
        ]
        detail_lines = [
            "📋 <b>Batafsil</b>",
            f"🆔 ID: {_tg_html(compact_id)}",
            f"📞 Telefon: {tel_disp}",
            f"🪪 Pasport: {pass_disp}",
            f"👨‍💼 Administrator: {admin_disp}",
            f"📝 Izoh: {izoh_disp}",
        ]
        if is_bron or convert_booking_id:
            ea = str(line.get("expectedArrival") or "").strip()
            if ea:
                detail_lines.append(f"⏰ Kelish: {_tg_html(ea[:120])}")
        detail_text = "\n".join(detail_lines)
        block_text = (
            "\n".join(header_lines)
            + "\n\n<blockquote expandable>\n"
            + detail_text
            + "\n</blockquote>"
        )

        photos_in = line.get("photos") if isinstance(line.get("photos"), list) else []
        photo_urls = [str(u) for u in photos_in if isinstance(u, str) and u.strip()][:3]
        mid: int | None = None
        try:
            if photo_urls:
                ok_img, root_mid = _telegram_send_channel_booking_images(block_text, photo_urls)
                mid = root_mid if ok_img and root_mid else _telegram_send_channel_html(block_text)
            else:
                mid = _telegram_send_channel_html(block_text)
        except Exception:
            logger.exception("Telegram kanal bron/check-in xabari")
            try:
                mid = _telegram_send_channel_html(block_text)
            except Exception:
                logger.exception("Telegram kanal matn zaxirasi")
                mid = None
        if mid:
            try:
                with connection.cursor() as cu:
                    _ensure_bed_bookings_telegram_channel_message_id_column(cu)
                    cu.execute(
                        "UPDATE bed_bookings SET telegram_channel_message_id = %s WHERE id = %s",
                        [int(mid), bid],
                    )
            except Exception:
                logger.exception("telegram_channel_message_id saqlanmadi")


def _notify_booking_channel_cancelled(
    *,
    hostel: str,
    room_code: str,
    room_name: str,
    bed_index: int,
    guest_name: str,
    booking_kind: str,
    reason: str,
    booking_id: str,
) -> None:
    kind_uz = "Bron" if booking_kind == "bron" else "Check-in"
    room_disp = (room_name or "").strip() or room_code
    text = "\n".join(
        [
            f"<b>⛔ Bekor qilindi</b> ({_tg_html(kind_uz)})",
            f"📍 {_tg_html(hostel)} · 🚪 {_tg_html(room_disp)} <code>({ _tg_html(room_code) })</code>",
            f"🛏 K<code>{int(bed_index)}</code>",
            f"👤 {_tg_html(guest_name or '—')}",
            f"📋 Sabab: {_tg_html(reason)}",
            f"🆔 <code>{_tg_html(str(booking_id)[:36])}</code>",
        ]
    )
    _telegram_send_channel_html(text)


def _telegram_validate_init_data(init_data_raw: str, bot_token: str) -> dict[str, Any] | None:
    parts = parse.parse_qsl(init_data_raw or "", keep_blank_values=True)
    if not parts:
        return None
    kv: dict[str, str] = {}
    recv_hash = ""
    for k, v in parts:
        if k == "hash":
            recv_hash = v
        else:
            kv[k] = v
    if not recv_hash:
        return None
    data_check_string = "\n".join(f"{k}={kv[k]}" for k in sorted(kv.keys()))
    secret = hmac.new(b"WebAppData", bot_token.encode("utf-8"), hashlib.sha256).digest()
    calc_hash = hmac.new(secret, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc_hash, recv_hash):
        return None
    user_raw = kv.get("user", "")
    if not user_raw:
        return None
    try:
        user_obj = json.loads(user_raw)
    except Exception:
        return None
    if not isinstance(user_obj, dict):
        return None
    uid = user_obj.get("id")
    if uid is None:
        return None
    try:
        user_obj["id"] = int(uid)
    except Exception:
        return None
    return user_obj


def _telegram_validate_login_widget_payload(payload: dict[str, Any], bot_token: str) -> dict[str, Any] | None:
    recv_hash = str(payload.get("hash") or "").strip()
    if not recv_hash:
        return None
    safe_fields: dict[str, str] = {}
    for key in ("id", "first_name", "last_name", "username", "photo_url", "auth_date"):
        v = payload.get(key)
        if v is None:
            continue
        safe_fields[key] = str(v)
    if "id" not in safe_fields or "auth_date" not in safe_fields:
        return None
    data_check_string = "\n".join(f"{k}={safe_fields[k]}" for k in sorted(safe_fields.keys()))
    secret_key = hashlib.sha256(bot_token.encode("utf-8")).digest()
    calc_hash = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc_hash, recv_hash):
        return None
    try:
        auth_date = int(safe_fields["auth_date"])
    except Exception:
        return None
    if auth_date <= 0 or (int(time.time()) - auth_date) > (24 * 60 * 60):
        return None
    try:
        uid = int(safe_fields["id"])
    except Exception:
        return None
    return {
        "id": uid,
        "first_name": safe_fields.get("first_name", ""),
        "last_name": safe_fields.get("last_name", ""),
        "username": safe_fields.get("username", ""),
        "photo_url": safe_fields.get("photo_url", ""),
    }


def _telegram_notify_super_admin_access_request(*, tg_id: int, display_name: str, username: str) -> None:
    token = str(os.environ.get("TELEGRAM_BOT_TOKEN", "") or "").strip()
    admin_ids = _super_admin_tg_ids()
    if not token or not admin_ids:
        return
    uname = f"@{username}" if username else "-"
    text = (
        "🛡 Yangi kirish so'rovi\n"
        f"👤 Ism: {_tg_html(display_name or '-')}\n"
        f"🔹 Username: {_tg_html(uname)}\n"
        f"🆔 Telegram ID: <code>{int(tg_id)}</code>\n\n"
        "Tasdiqlash uchun ilovada `Profile → Jamoa` bo'limidan userni faol qiling."
    )
    for admin_id in admin_ids:
        try:
            _telegram_post(token, "sendMessage", {"chat_id": str(admin_id), "text": text})
        except Exception:
            continue
    ch = (
        "<b>🛡 Yangi kirish so'rovi (Telegram)</b>\n"
        f"👤 {_tg_html(display_name or '-')}\n"
        f"🔹 {_tg_html(uname)}\n"
        f"🆔 <code>{int(tg_id)}</code>\n"
        "Jamoada foydalanuvchini <b>faol</b> qiling."
    )
    _telegram_send_channel_html(ch)


def _auth_token_issue(payload: dict[str, Any]) -> str:
    return signing.dumps(payload, salt=AUTH_TOKEN_SALT, compress=True)


def _auth_token_parse(token: str) -> dict[str, Any] | None:
    try:
        obj = signing.loads(token, salt=AUTH_TOKEN_SALT, max_age=AUTH_TOKEN_MAX_AGE_SEC)
    except Exception:
        return None
    return obj if isinstance(obj, dict) else None


def _request_auth(req) -> dict[str, Any] | None:
    h = str(req.META.get("HTTP_AUTHORIZATION") or "").strip()
    if not h.lower().startswith("bearer "):
        return None
    tok = h[7:].strip()
    if not tok:
        return None
    return _auth_token_parse(tok)


def _require_auth(req) -> tuple[dict[str, Any] | None, JsonResponse | None]:
    auth = _request_auth(req)
    if auth is None:
        return None, JsonResponse({"error": "Unauthorized"}, status=401)
    return auth, None


def _require_super_admin(req) -> tuple[dict[str, Any] | None, JsonResponse | None]:
    auth, err = _require_auth(req)
    if err:
        return None, err
    role = str((auth or {}).get("role") or "")
    if role != "super_admin":
        return None, JsonResponse({"error": "Forbidden"}, status=403)
    return auth, None


def _auth_telegram_upsert_and_issue(
    *, tg_id: int, display_name: str, username: str, preferred_role: str, photo_url: str = ""
) -> JsonResponse:
    role = preferred_role if preferred_role in ("super_admin", "admin", "staff") else "staff"
    with connection.cursor() as c:
        _ensure_users_auth_schema(c)
        c.execute(
            """
            SELECT id, role, display_name, active
            FROM users
            WHERE telegram_user_id = %s
            LIMIT 1
            """,
            [tg_id],
        )
        row = c.fetchone()
        if row:
            user_id = int(row[0])
            db_role = str(row[1] or "staff")
            db_active = bool(row[3])
            effective_role = "super_admin" if role == "super_admin" else db_role
            if not db_active:
                if role == "super_admin":
                    c.execute(
                        """
                        UPDATE users
                        SET display_name = %s,
                            auth_provider = 'telegram',
                            role = 'super_admin',
                            active = TRUE
                        WHERE id = %s
                        """,
                        [display_name, user_id],
                    )
                    effective_role = "super_admin"
                else:
                    _telegram_notify_super_admin_access_request(
                        tg_id=tg_id, display_name=display_name, username=username
                    )
                    return JsonResponse(
                        {"error": "So'rov yuborildi. SuperAdminga murojaat qiling."}, status=403
                    )
            c.execute(
                """
                UPDATE users
                SET display_name = %s,
                    auth_provider = 'telegram',
                    role = %s,
                    avatar_url = CASE
                        WHEN (avatar_url IS NULL OR avatar_url = '') THEN %s
                        ELSE avatar_url
                    END
                WHERE id = %s
                """,
                [display_name, effective_role, photo_url or None, user_id],
            )
            role = effective_role
        else:
            login_seed = username or f"tg_{tg_id}"
            login_seed = re.sub(r"[^a-z0-9._-]+", "_", login_seed).strip("_") or f"tg_{tg_id}"
            login_l = login_seed[:58]
            for i in range(40):
                cand = login_l if i == 0 else f"{login_l[:52]}_{i}"
                c.execute("SELECT 1 FROM users WHERE login = %s", [cand])
                if not c.fetchone():
                    login_l = cand
                    break
            password_hash = bcrypt.hashpw(secrets.token_urlsafe(18).encode("utf-8"), bcrypt.gensalt(10)).decode("ascii")
            c.execute(
                """
                INSERT INTO users (login, display_name, password_hash, role, active, telegram_user_id, auth_provider, avatar_url)
                VALUES (%s, %s, %s, %s, %s, %s, 'telegram', %s)
                RETURNING id
                """,
                [login_l, display_name, password_hash, role, bool(role == "super_admin"), tg_id, photo_url or None],
            )
            user_id = int(c.fetchone()[0])
            if role != "super_admin":
                _telegram_notify_super_admin_access_request(
                    tg_id=tg_id, display_name=display_name, username=username
                )
                return JsonResponse(
                    {"error": "So'rov yuborildi. SuperAdminga murojaat qiling."}, status=403
                )

    final_avatar = ""
    with connection.cursor() as c2:
        _ensure_users_auth_schema(c2)
        c2.execute("SELECT COALESCE(avatar_url, '') FROM users WHERE id = %s LIMIT 1", [user_id])
        r2 = c2.fetchone()
        if r2:
            final_avatar = str(r2[0] or "")

    token = _auth_token_issue(
        {
            "uid": user_id,
            "telegram_user_id": tg_id,
            "role": role,
            "display_name": display_name,
        }
    )
    return JsonResponse(
        {
            "token": token,
            "user": {
                "id": user_id,
                "telegram_user_id": tg_id,
                "display_name": display_name,
                "role": role,
                "avatar_url": final_avatar,
            },
        }
    )

def _money_int_text(val: Any) -> str:
    """Narx / to‘lov — JSON va taxta uchun butun `som` matn (76000.0 → 76000, 760000 emas)."""
    try:
        f = float(val or 0)
    except (TypeError, ValueError):
        return "0"
    if f != f:  # NaN
        return "0"
    return str(int(round(f)))


def format_phone(raw: str) -> str:
    if not raw:
        return ""
    s = str(raw).strip()
    if s.startswith("+"):
        s = s[1:]
    d = re.sub(r"\D", "", s)
    return f"+{d}" if d else ""


def format_guest_contact(raw: str) -> str:
    """Taxta: raqamli telefon → `format_phone`, aks holda (pasport seriyasi) matn."""
    s = re.sub(r"\s+", "", (raw or "").strip())
    if not s:
        return ""
    if re.fullmatch(r"NIU[A-Z0-9]{4,}", s, flags=re.I):
        return ""
    if re.fullmatch(r"\d{5,32}", s):
        return format_phone(s)
    return s[:40]


def _json_error(msg: str, status: int = 400) -> JsonResponse:
    return JsonResponse({"error": msg}, status=status)


def _read_json(request) -> dict[str, Any] | None:
    if not request.body:
        return {}
    try:
        out = json.loads(request.body.decode())
        return out if isinstance(out, dict) else None
    except json.JSONDecodeError:
        return None


def _today_iso() -> str:
    return date.today().isoformat()


def _prune_old_cleaning_photos(cursor: Any) -> None:
    """Tozalikdagi avval/keyin rasmlarini 5 kundan keyin avtomatik tozalaydi."""
    cursor.execute(
        """
        UPDATE room_cleaning
        SET photos_before = '[]',
            photos_after = '[]'
        WHERE updated_at <= (CURRENT_TIMESTAMP - (%s * INTERVAL '1 day'))
          AND (
            COALESCE(photos_before, '[]') <> '[]'
            OR COALESCE(photos_after, '[]') <> '[]'
          )
        """,
        [CLEANING_PHOTO_RETENTION_DAYS],
    )


def _resolve_room(hostel_name: str, room_code: str) -> dict[str, Any] | None:
    with connection.cursor() as c:
        c.execute(
            """
            SELECT r.id, r.bed_count, r.room_kind
            FROM rooms r
            JOIN hostels h ON h.id = r.hostel_id
            WHERE h.name = %s AND r.code = %s
            """,
            [hostel_name, room_code],
        )
        row = c.fetchone()
        if not row:
            return None
        return {"id": row[0], "bed_count": row[1], "room_kind": row[2]}


def _resolve_booking_line_identity(line: dict[str, Any]) -> tuple[str | None, str | None, str, str]:
    """(identity_key, error_message, phone_raw, passport_raw). `ik` None — check_in, mehmon hujjati yo‘q."""
    raw_kind = str(line.get("bookingKind") or line.get("booking_kind") or "check_in").lower()
    is_bron = raw_kind == "bron"
    phone_raw = str(line.get("guestPhone") or "")
    passport_raw = str(line.get("guestPassportSeries") or "")
    ik, id_err = compute_identity_key(phone_raw, passport_raw)
    if ik:
        return ik, None, phone_raw, passport_raw
    if is_bron:
        return None, id_err or "Mehmon identifikatori noto‘g‘ri", phone_raw, passport_raw
    return None, None, phone_raw, passport_raw


def _has_overlap(
    room_id: int,
    bed_index: int,
    check_in: str,
    nights: int,
    exclude_booking_id: str | None = None,
) -> bool:
    with connection.cursor() as c:
        c.execute(
            """
            SELECT 1
            FROM bed_bookings b
            WHERE b.room_id = %s AND b.bed_index = %s AND b.status = 'active'
              AND (%s IS NULL OR b.id <> %s)
              AND CAST(NULLIF(b.check_in_date, '') AS date) <= (CAST(%s AS date) + ((%s - 1) * INTERVAL '1 day'))
              AND CAST(%s AS date) <= (CAST(NULLIF(b.check_in_date, '') AS date) + ((COALESCE(b.nights, 1) - 1) * INTERVAL '1 day'))
            LIMIT 1
            """,
            [room_id, bed_index, exclude_booking_id, exclude_booking_id, check_in, nights, check_in],
        )
        return c.fetchone() is not None


def _find_active_overlap_booking(
    room_id: int,
    bed_index: int,
    check_in: str,
    nights: int,
    exclude_booking_id: str | None = None,
) -> dict[str, Any] | None:
    with connection.cursor() as c:
        c.execute(
            """
            SELECT CAST(b.id AS TEXT), COALESCE(b.booking_kind, 'check_in')
            FROM bed_bookings b
            WHERE b.room_id = %s AND b.bed_index = %s AND b.status = 'active'
              AND (%s IS NULL OR b.id <> %s)
              AND CAST(NULLIF(b.check_in_date, '') AS date) <= (CAST(%s AS date) + ((%s - 1) * INTERVAL '1 day'))
              AND CAST(%s AS date) <= (CAST(NULLIF(b.check_in_date, '') AS date) + ((COALESCE(b.nights, 1) - 1) * INTERVAL '1 day'))
            ORDER BY b.updated_at DESC
            LIMIT 1
            """,
            [room_id, bed_index, exclude_booking_id, exclude_booking_id, check_in, nights, check_in],
        )
        row = c.fetchone()
        if not row:
            return None
        return {"id": str(row[0]), "booking_kind": str(row[1] or "check_in")}


@csrf_exempt
@require_http_methods(["GET"])
def health(_request):
    return JsonResponse({"ok": True, "service": "swift-bookings-api"})


@csrf_exempt
@require_http_methods(["POST"])
def doc_parse(request):
    body = _read_json(request)
    if body is None:
        return _json_error("Maʼlumot formati buzilgan (JSON).")
    photo = str((body.get("photo") if isinstance(body, dict) else "") or "").strip()
    if not photo:
        return _json_error("photo majburiy", 400)
    doc, raw_text = parse_document_fields_from_photo_with_raw(photo)
    if not doc:
        return JsonResponse({"ok": True, "parsed": False, "rawExtractedText": raw_text})
    return JsonResponse(
        {
            "ok": True,
            "parsed": True,
            "fullName": str(doc.get("doc_full_name") or ""),
            "birthDate": str(doc.get("doc_birth_date") or ""),
            "expiryDate": str(doc.get("doc_expiry_date") or ""),
            "citizenship": str(doc.get("doc_citizenship") or ""),
            "documentNumber": str(doc.get("doc_number") or ""),
            "documentType": str(doc.get("doc_type") or ""),
            "rawExtractedText": raw_text,
        }
    )


@csrf_exempt
@require_http_methods(["GET"])
def board(request):
    hostel = request.GET.get("hostel") or "Vodnik"
    d = request.GET.get("date") or ""
    date_iso = d if ISO_DATE.match(d) else _today_iso()

    with connection.cursor() as c:
        ensure_guest_schema(c)
        c.execute(
            """
            SELECT r.code, rc.status, COALESCE(CAST(rc.full_taken AS integer), 0), COALESCE(rc.full_taken_mode, '')
            FROM rooms r
            JOIN hostels h ON h.id = r.hostel_id
            LEFT JOIN room_cleaning rc ON rc.room_id = r.id
            WHERE h.name = %s AND r.room_kind = 'dorm'
            ORDER BY r.id
            """,
            [hostel],
        )
        cleaning_by: dict[str, str] = {}
        full_taken_by: dict[str, bool] = {}
        full_taken_mode_by: dict[str, str] = {}
        for code, status, full_taken, full_taken_mode in c.fetchall():
            cleaning_by[code] = "clean" if status == "cleaned" else "dirty"
            full_taken_by[code] = bool(int(full_taken or 0))
            mode = str(full_taken_mode or "").strip().lower()
            full_taken_mode_by[code] = mode if mode in ("check_in", "bron") else ""

        c.execute(
            """
            SELECT CAST(COALESCE(SUM(r.bed_count), 0) AS TEXT)
            FROM rooms r
            JOIN hostels h ON h.id = r.hostel_id
            WHERE h.name = %s AND r.room_kind = 'dorm'
            """,
            [hostel],
        )
        total_beds = int(c.fetchone()[0] or 0)

        c.execute(
            """
            SELECT CAST(COUNT(*) AS TEXT),
                   CAST(COALESCE(SUM(CASE WHEN b.price > b.paid THEN b.price - b.paid ELSE 0 END), 0) AS TEXT),
                   CAST(COALESCE(SUM(b.paid), 0) AS TEXT)
            FROM bed_bookings b
            JOIN rooms r ON r.id = b.room_id
            JOIN hostels h ON h.id = r.hostel_id
            WHERE h.name = %s AND r.room_kind = 'dorm' AND b.status = 'active'
              AND CAST(NULLIF(b.check_in_date, '') AS date) <= CAST(%s AS date)
              AND CAST(%s AS date) < (CAST(NULLIF(b.check_in_date, '') AS date) + (COALESCE(b.nights, 1) * INTERVAL '1 day'))
            """,
            [hostel, date_iso, date_iso],
        )
        agg = c.fetchone()
        occ_guests = int(agg[0] or 0)
        debt_num = float(agg[1] or 0)
        revenue_num = float(agg[2] or 0)

        stats = {
            "empty": max(0, total_beds - occ_guests),
            "guests": occ_guests,
            "debt": round(debt_num),
            "revenue": round(revenue_num),
        }

        c.execute(
            """
            SELECT r.code, b.bed_index, b.guest_name, b.guest_phone, b.checked_in_by,
                   CAST(b.id AS TEXT) AS booking_id,
                   CAST(b.price AS TEXT) AS price,
                   CAST(b.paid AS TEXT) AS paid,
                   b.notes,
                   b.nights,
                   b.check_in_date AS check_in_date,
                   b.photos,
                   b.created_at AS created_at,
                   COALESCE(b.booking_kind, 'check_in') AS booking_kind,
                   COALESCE(b.expected_arrival, '') AS expected_arrival
            FROM bed_bookings b
            JOIN rooms r ON r.id = b.room_id
            JOIN hostels h ON h.id = r.hostel_id
            WHERE h.name = %s AND r.room_kind = 'dorm' AND b.status = 'active'
              AND CAST(NULLIF(b.check_in_date, '') AS date) <= CAST(%s AS date)
              AND CAST(%s AS date) < (CAST(NULLIF(b.check_in_date, '') AS date) + (COALESCE(b.nights, 1) * INTERVAL '1 day'))
            """,
            [hostel, date_iso, date_iso],
        )
        bookings = []
        for row in c.fetchall():
            photos_raw = row[11]
            if isinstance(photos_raw, list):
                photos = photos_raw
            elif isinstance(photos_raw, str):
                try:
                    j = json.loads(photos_raw)
                    photos = j if isinstance(j, list) else []
                except json.JSONDecodeError:
                    photos = []
            else:
                photos = []
            cin = row[10]
            check_in_str = cin if isinstance(cin, str) else str(cin) if cin is not None else ""
            created_raw = row[12]
            checked_in_at = (
                str(created_raw).strip()
                if created_raw is not None and str(created_raw).strip()
                else ""
            )
            kind_raw = str(row[13] or "").strip().lower()
            booking_kind = "bron" if kind_raw == "bron" else "check_in"
            expected_arrival = str(row[14] or "").strip()
            bookings.append(
                {
                    "roomCode": row[0],
                    "bedIndex": row[1],
                    "guestName": row[2] or "",
                    "guestPhone": format_guest_contact(row[3] or ""),
                    "checkedInBy": row[4] or "",
                    "bookingId": row[5],
                    "price": _money_int_text(row[6]),
                    "paid": _money_int_text(row[7]),
                    "notes": row[8] or "",
                    "nights": row[9],
                    "checkInDate": check_in_str,
                    "checkedInAt": checked_in_at,
                    "photos": photos,
                    "bookingKind": booking_kind,
                    "expectedArrival": expected_arrival,
                }
            )

    return JsonResponse(
        {
            "hostel": hostel,
            "date": date_iso,
            "stats": stats,
            "bookings": bookings,
            "cleaningByRoomCode": cleaning_by,
            "fullTakenByRoomCode": full_taken_by,
            "fullTakenModeByRoomCode": full_taken_mode_by,
        }
    )


@csrf_exempt
@require_http_methods(["GET", "HEAD", "POST"])
def users(request):
    _auth, auth_err = _require_super_admin(request)
    if auth_err:
        return auth_err
    if request.method in ("GET", "HEAD"):
        with connection.cursor() as c:
            _ensure_users_auth_schema(c)
            c.execute(
                """
                SELECT id, login, display_name, role, active, created_at,
                       COALESCE(auth_provider, 'password'), telegram_user_id, avatar_url
                FROM users
                ORDER BY active DESC, login ASC
                """
            )
            rows = [
                {
                    "id": r[0],
                    "login": r[1],
                    "display_name": r[2],
                    "role": r[3],
                    "active": bool(r[4]),
                    "created_at": r[5] or "",
                    "auth_provider": str(r[6] or "password"),
                    "telegram_user_id": int(r[7]) if r[7] is not None else None,
                    "avatar_url": str(r[8] or ""),
                }
                for r in c.fetchall()
            ]
        return JsonResponse({"users": rows})

    body = _read_json(request)
    if body is None:
        return _json_error("Invalid JSON")
    login = (body.get("login") or "").strip()
    display_name = (body.get("display_name") or "").strip()
    password = body.get("password") or ""
    role = body.get("role") or "staff"
    if len(login) < 2 or len(login) > 64 or not LOGIN_RE.match(login):
        return _json_error("Invalid login", 400)
    if not display_name or len(display_name) > 120:
        return _json_error("Invalid display_name", 400)
    if len(password) < 6 or len(password) > 128:
        return _json_error("Invalid password", 400)
    if role not in ("admin", "staff"):
        return _json_error("Invalid role", 400)
    pw_hash = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(10)).decode("ascii")
    login_l = login.lower()
    try:
        with connection.cursor() as c:
            _ensure_users_auth_schema(c)
            c.execute(
                "INSERT INTO users (login, display_name, password_hash, role) VALUES (%s, %s, %s, %s) RETURNING id",
                [login_l, display_name, pw_hash, role],
            )
            new_id = c.fetchone()[0]
    except IntegrityError:
        return _json_error("Bu login allaqachon mavjud", 409)
    return JsonResponse({"id": new_id, "login": login_l}, status=201)


def _users_patch(request, user_id: int):
    _auth, auth_err = _require_super_admin(request)
    if auth_err:
        return auth_err
    body = _read_json(request)
    if body is None:
        return _json_error("Invalid JSON")
    sets: list[str] = []
    vals: list[Any] = []
    if "login" in body:
        lg = (body.get("login") or "").strip().lower()
        if len(lg) < 2 or len(lg) > 64 or not LOGIN_RE.match(lg):
            return _json_error("Invalid login", 400)
        sets.append("login = %s")
        vals.append(lg)
    if "display_name" in body:
        dn = (body.get("display_name") or "").strip()
        if not dn or len(dn) > 120:
            return _json_error("Invalid display_name", 400)
        sets.append("display_name = %s")
        vals.append(dn)
    if "password" in body:
        pw = body.get("password") or ""
        if len(pw) < 6 or len(pw) > 128:
            return _json_error("Invalid password", 400)
        sets.append("password_hash = %s")
        vals.append(bcrypt.hashpw(pw.encode("utf-8"), bcrypt.gensalt(10)).decode("ascii"))
    if "role" in body:
        role = body.get("role")
        if role not in ("super_admin", "admin", "staff"):
            return _json_error("Invalid role", 400)
        sets.append("role = %s")
        vals.append(role)
    if "active" in body:
        sets.append("active = %s")
        vals.append(bool(body.get("active")))
    if "avatar_url" in body:
        av_raw = body.get("avatar_url")
        av = "" if av_raw is None else str(av_raw)
        if av and len(av) > 1_500_000:
            return _json_error("Rasm hajmi juda katta", 413)
        sets.append("avatar_url = %s")
        vals.append(av or None)
    if not sets:
        return JsonResponse({"ok": True, "updated": False})
    vals.append(user_id)
    try:
        with connection.cursor() as c:
            c.execute(f"UPDATE users SET {', '.join(sets)} WHERE id = %s", vals)
            if c.rowcount == 0:
                return _json_error("Foydalanuvchi topilmadi", 404)
    except IntegrityError:
        return _json_error("Bu login allaqachon mavjud", 409)
    return JsonResponse({"ok": True, "updated": True})


def _users_delete(_request, user_id: int):
    with connection.cursor() as c:
        _ensure_users_auth_schema(c)
        c.execute("UPDATE users SET active = FALSE WHERE id = %s AND active = TRUE", [user_id])
        if c.rowcount == 0:
            return _json_error("Faol foydalanuvchi topilmadi", 404)
    return JsonResponse({"ok": True})


@csrf_exempt
@require_http_methods(["PATCH", "DELETE"])
def user_detail(request, user_id: int):
    _auth, auth_err = _require_super_admin(request)
    if auth_err:
        return auth_err
    if request.method == "PATCH":
        return _users_patch(request, user_id)
    return _users_delete(request, user_id)


@csrf_exempt
@require_http_methods(["POST"])
def auth_telegram(request):
    body = _read_json(request)
    if body is None:
        return _json_error("Invalid JSON")
    init_data = str(body.get("initData") or "").strip()
    if not init_data:
        return _json_error("initData majburiy", 400)
    bot_token = str(os.environ.get("TELEGRAM_BOT_TOKEN", "") or "").strip()
    if not bot_token:
        return _json_error("Serverda TELEGRAM_BOT_TOKEN topilmadi", 500)
    tg_user = _telegram_validate_init_data(init_data, bot_token)
    if tg_user is None:
        return _json_error("Telegram initData yaroqsiz", 401)

    tg_id = int(tg_user.get("id"))
    first_name = str(tg_user.get("first_name") or "").strip()
    last_name = str(tg_user.get("last_name") or "").strip()
    username = str(tg_user.get("username") or "").strip().lower()
    photo_url = str(tg_user.get("photo_url") or "").strip()
    display_name = " ".join([x for x in [first_name, last_name] if x]).strip() or (username or f"tg-{tg_id}")
    role = "super_admin" if tg_id in _super_admin_tg_ids() else "staff"
    return _auth_telegram_upsert_and_issue(
        tg_id=tg_id, display_name=display_name, username=username, preferred_role=role, photo_url=photo_url
    )


@csrf_exempt
@require_http_methods(["POST"])
def auth_telegram_login(request):
    body = _read_json(request)
    if body is None or not isinstance(body, dict):
        return _json_error("Invalid payload", 400)
    bot_token = str(os.environ.get("TELEGRAM_BOT_TOKEN", "") or "").strip()
    if not bot_token:
        return _json_error("Serverda TELEGRAM_BOT_TOKEN topilmadi", 500)
    tg_user = _telegram_validate_login_widget_payload(body, bot_token)
    if tg_user is None:
        return _json_error("Telegram login maʼlumotlari yaroqsiz", 401)
    tg_id = int(tg_user.get("id") or 0)
    first_name = str(tg_user.get("first_name") or "").strip()
    last_name = str(tg_user.get("last_name") or "").strip()
    username = str(tg_user.get("username") or "").strip().lower()
    photo_url = str(tg_user.get("photo_url") or "").strip()
    display_name = " ".join([x for x in [first_name, last_name] if x]).strip() or (username or f"tg-{tg_id}")
    role = "super_admin" if tg_id in _super_admin_tg_ids() else "staff"
    return _auth_telegram_upsert_and_issue(
        tg_id=tg_id, display_name=display_name, username=username, preferred_role=role, photo_url=photo_url
    )


@csrf_exempt
@require_http_methods(["POST"])
def auth_password_login(request):
    body = _read_json(request)
    if body is None:
        return _json_error("Invalid JSON")
    login_l = str(body.get("login") or "").strip().lower()
    password = str(body.get("password") or "")
    if len(login_l) < 2 or len(login_l) > 64:
        return _json_error("Login noto'g'ri", 400)
    if len(password) < 1 or len(password) > 128:
        return _json_error("Parol noto'g'ri", 400)

    with connection.cursor() as c:
        _ensure_users_auth_schema(c)
        c.execute(
            """
            SELECT id, display_name, role, active, password_hash, COALESCE(telegram_user_id, 0)
            FROM users
            WHERE lower(login) = %s
            LIMIT 1
            """,
            [login_l],
        )
        row = c.fetchone()
    if not row:
        return _json_error("Login yoki parol xato", 401)

    user_id = int(row[0])
    display_name = str(row[1] or login_l)
    role = str(row[2] or "staff")
    active = bool(row[3])
    pw_hash = str(row[4] or "")
    tg_id = int(row[5] or 0)

    if not active:
        return _json_error("Foydalanuvchi nofaol", 403)
    try:
        ok = bcrypt.checkpw(password.encode("utf-8"), pw_hash.encode("ascii"))
    except Exception:
        ok = False
    if not ok:
        return _json_error("Login yoki parol xato", 401)

    token = _auth_token_issue(
        {"uid": user_id, "telegram_user_id": tg_id, "role": role, "display_name": display_name}
    )
    return JsonResponse(
        {
            "token": token,
            "user": {
                "id": user_id,
                "telegram_user_id": tg_id,
                "display_name": display_name,
                "role": role,
            },
        }
    )


@csrf_exempt
@require_http_methods(["GET", "PATCH"])
def auth_me(request):
    auth, auth_err = _require_auth(request)
    if auth_err:
        return auth_err
    user_id = int(auth.get("uid") or 0)
    if user_id <= 0:
        return _json_error("Unauthorized", 401)

    if request.method == "PATCH":
        body = _read_json(request)
        if body is None:
            return _json_error("Invalid JSON")
        sets: list[str] = []
        vals: list[Any] = []
        if "avatar_url" in body:
            av_raw = body.get("avatar_url")
            av = "" if av_raw is None else str(av_raw)
            if av and len(av) > 1_500_000:
                return _json_error("Rasm hajmi juda katta", 413)
            sets.append("avatar_url = %s")
            vals.append(av or None)
        if "display_name" in body:
            dn = (body.get("display_name") or "").strip()
            if not dn or len(dn) > 120:
                return _json_error("Invalid display_name", 400)
            sets.append("display_name = %s")
            vals.append(dn)
        if sets:
            vals.append(user_id)
            with connection.cursor() as c:
                _ensure_users_auth_schema(c)
                c.execute(f"UPDATE users SET {', '.join(sets)} WHERE id = %s", vals)

    with connection.cursor() as c:
        _ensure_users_auth_schema(c)
        c.execute(
            """
            SELECT id, display_name, role, COALESCE(telegram_user_id, 0), avatar_url
            FROM users
            WHERE id = %s
            LIMIT 1
            """,
            [user_id],
        )
        row = c.fetchone()
    if not row:
        return _json_error("Foydalanuvchi topilmadi", 404)

    return JsonResponse(
        {
            "user": {
                "id": int(row[0]),
                "display_name": str(row[1] or ""),
                "role": str(row[2] or "staff"),
                "telegram_user_id": int(row[3] or 0),
                "avatar_url": str(row[4] or ""),
            }
        }
    )


@csrf_exempt
@require_http_methods(["POST"])
def bookings_create(request):
    body = _read_json(request)
    if body is None:
        return _json_error("Maʼlumot formati buzilgan (JSON).")
    hostel = body.get("hostel") or ""
    room_code = body.get("roomCode") or ""
    check_in_date = body.get("checkInDate") or ""
    nights = body.get("nights")
    checked_in_body = str(body.get("checkedInBy") or "").strip()
    auth_req = _request_auth(request)
    if auth_req:
        dn = str(auth_req.get("display_name") or "").strip()
        checked_in_by = (dn[:120] if dn else checked_in_body[:120])
    else:
        checked_in_by = checked_in_body[:120]
    lines = body.get("lines")
    if not hostel or not room_code or not ISO_DATE.match(check_in_date):
        return _json_error("Filial, xona yoki kirish sanasi noto‘g‘ri yoki yetishmayapti.", 400)
    if not isinstance(nights, int) or nights < 1 or nights > 365:
        nights = 1
    if not isinstance(lines, list) or len(lines) < 1:
        return _json_error("Kamida bitta mehmon qatori kerak.", 400)
    if len(checked_in_by) > 120:
        return _json_error("«Kim check-in qildi» matni 120 belgidan oshmasin.", 400)

    room = _resolve_room(hostel, room_code)
    if not room or room["room_kind"] != "dorm":
        return _json_error("Xona topilmadi yoki bu turdagi xona emas.", 404)
    bed_count = int(room["bed_count"])
    room_id = int(room["id"])

    identities_batch: list[str] = []
    resolved_lines: list[tuple[str | None, str, str, str | None]] = []
    identity_overlap_warnings: list[dict[str, Any]] = []
    with connection.cursor() as c0:
        ensure_guest_schema(c0)

    for line in lines:
        if not isinstance(line, dict):
            return _json_error("Mehmon qatori noto‘g‘ri.", 400)
        bi = line.get("bedIndex")
        if not isinstance(bi, int) or bi < 1:
            return _json_error("Karavot raqami musbat butun son bo‘lishi kerak.", 400)
        if bi > bed_count:
            return _json_error(f"Bu xonada karavot raqami 1 dan {bed_count} gacha bo‘lishi mumkin.", 400)
        raw_kind = str(line.get("bookingKind") or line.get("booking_kind") or "check_in").lower()
        if raw_kind not in ("bron", "check_in"):
            return _json_error("bookingKind faqat 'bron' yoki 'check_in'", 400)
        ik, err_msg, phone_raw, passport_raw = _resolve_booking_line_identity(line)
        if err_msg:
            return _json_error(err_msg, 400)
        ln = line.get("nights")
        line_nights = int(ln) if isinstance(ln, int) and 1 <= ln <= 365 else nights
        overlap = _find_active_overlap_booking(room_id, bi, check_in_date, line_nights, None)
        convert_booking_id: str | None = None
        if overlap is not None:
            overlap_kind = str(overlap.get("booking_kind") or "check_in").strip().lower()
            if raw_kind == "check_in" and overlap_kind == "bron":
                convert_booking_id = str(overlap["id"])
            else:
                return _json_error(
                    f"{bi}-karavot ushbu sanalar uchun allaqachon band. Boshqa bo‘sh karavot yoki boshqa kunni tanlang.",
                    409,
                )
        if ik is not None:
            overlap_detail = identity_hostel_active_stay_overlap_detail(
                hostel, ik, check_in_date, line_nights, None
            )
            if overlap_detail is not None:
                identity_overlap_warnings.append(overlap_detail)
        identities_batch.append(ik if ik is not None else f"__anon:{uuid.uuid4()}")
        resolved_lines.append((ik, phone_raw, passport_raw, convert_booking_id))
    if len(identities_batch) != len(set(identities_batch)):
        return _json_error("Bitta bron so‘rovida bir xil mehmon (telefon/pasport) takrorlanmasin", 400)

    inserted: list[str] = []
    with transaction.atomic():
        with connection.cursor() as c:
            ensure_guest_schema(c)
            for line, (ik, phone_raw, passport_raw, convert_booking_id) in zip(lines, resolved_lines):
                bi = int(line["bedIndex"])
                ln = line.get("nights")
                line_nights = int(ln) if isinstance(ln, int) and 1 <= ln <= 365 else nights
                raw_kind = str(line.get("bookingKind") or line.get("booking_kind") or "check_in").lower()
                line_booking_kind = "bron" if raw_kind == "bron" else "check_in"
                expected_arrival = (
                    str(line.get("expectedArrival") or "")[:120] if line_booking_kind == "bron" else ""
                )
                photos = line.get("photos") if isinstance(line.get("photos"), list) else []
                if ik is None:
                    guest_name = str(line.get("guestName") or "").strip()[:200]
                    gid = None
                    gp = ""
                else:
                    pn = normalize_phone_digits(phone_raw)
                    ps = normalize_passport_series(passport_raw)
                    guest_name = resolve_guest_name_for_line(line, ik, pn)
                    gid = upsert_guest(c, ik, pn, ps, guest_name or "Mehmon")
                    gp = guest_phone_column_value(ik, pn, ps)
                if gid and photos:
                    doc = parse_document_fields_from_photo(str(photos[0] or ""))
                    if doc:
                        upsert_guest_document_fields(c, int(gid), doc)
                if convert_booking_id is not None:
                    c.execute(
                        """
                        UPDATE bed_bookings
                           SET check_in_date = %s,
                               nights = %s,
                               guest_name = %s,
                               guest_phone = %s,
                               guest_id = %s,
                               price = %s,
                               paid = %s,
                               notes = %s,
                               photos = %s,
                               checked_in_by = %s,
                               booking_kind = 'check_in',
                               expected_arrival = '',
                               updated_at = CURRENT_TIMESTAMP
                         WHERE id = %s AND status = 'active'
                        """,
                        [
                            check_in_date,
                            line_nights,
                            guest_name,
                            gp,
                            gid,
                            _money_int_text(line.get("price", "")),
                            _money_int_text(line.get("paid", "")),
                            (line.get("notes") or "")[:2000],
                            json.dumps(photos[:20]),
                            (checked_in_by or "")[:120],
                            convert_booking_id,
                        ],
                    )
                    inserted.append(convert_booking_id)
                else:
                    bid = str(uuid.uuid4())
                    c.execute(
                        """
                        INSERT INTO bed_bookings (
                          id, room_id, bed_index, check_in_date, nights, guest_name, guest_phone,
                          guest_id, price, paid, notes, photos, checked_in_by, status,
                          booking_kind, expected_arrival
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'active', %s, %s)
                        RETURNING CAST(id AS TEXT)
                        """,
                        [
                            bid,
                            room_id,
                            bi,
                            check_in_date,
                            line_nights,
                            guest_name,
                            gp,
                            gid,
                            _money_int_text(line.get("price", "")),
                            _money_int_text(line.get("paid", "")),
                            (line.get("notes") or "")[:2000],
                            json.dumps(photos[:20]),
                            (checked_in_by or "")[:120],
                            line_booking_kind,
                            expected_arrival,
                        ],
                    )
                    inserted.append(c.fetchone()[0])
    try:
        _notify_booking_channel_after_create(
            hostel=hostel,
            room_code=room_code,
            check_in_date=check_in_date,
            nights=nights,
            checked_in_by=checked_in_by,
            lines=lines,
            inserted_ids=inserted,
            resolved_lines=resolved_lines,
        )
    except Exception:
        logger.exception("Telegram kanal bildirishnomasi (create) ishlamadi")
    return JsonResponse(
        {"ids": inserted, "identityOverlapWarnings": identity_overlap_warnings},
        status=201,
    )


def _bookings_patch(request, booking_id: uuid.UUID):
    body = _read_json(request)
    if body is None:
        return _json_error("Maʼlumot formati buzilgan (JSON).")
    bid = str(booking_id)
    before_snap: dict[str, Any] = {}
    tg_reply_mid = 0
    with connection.cursor() as c:
        ensure_guest_schema(c)
        _ensure_bed_bookings_telegram_channel_message_id_column(c)
        c.execute(
            """
            SELECT b.room_id, b.bed_index, b.check_in_date, b.nights, b.guest_name, b.guest_phone,
                   b.guest_id, h.name, COALESCE(b.booking_kind, 'check_in'),
                   b.price, b.paid, b.notes, b.photos, b.checked_in_by,
                   COALESCE(b.telegram_channel_message_id, 0)
            FROM bed_bookings b
            JOIN rooms r ON r.id = b.room_id
            JOIN hostels h ON h.id = r.hostel_id
            WHERE b.id = %s AND b.status = 'active'
            """,
            [bid],
        )
        cur = c.fetchone()
        if not cur:
            return _json_error("Yozuv topilmadi yoki u allaqachon yopilgan.", 404)
        (
            room_id,
            bed_index,
            check_in_date,
            cur_nights,
            cur_guest_name,
            cur_guest_phone,
            cur_guest_id,
            hostel_name,
            cur_booking_kind_raw,
            cur_price,
            cur_paid,
            cur_notes,
            cur_photos,
            cur_checked_in_by,
            cur_telegram_mid,
        ) = (
            int(cur[0]),
            int(cur[1]),
            cur[2],
            int(cur[3]),
            str(cur[4] or ""),
            str(cur[5] or ""),
            cur[6],
            str(cur[7] or ""),
            str(cur[8] or "check_in"),
            cur[9],
            cur[10],
            cur[11],
            cur[12],
            str(cur[13] or ""),
            int(cur[14] or 0),
        )
        cur_booking_kind = "bron" if str(cur_booking_kind_raw or "").strip().lower() == "bron" else "check_in"
        before_snap = _booking_telegram_snapshot_row(
            check_in_date,
            cur_nights,
            cur_guest_name,
            cur_guest_phone,
            cur_price,
            cur_paid,
            cur_notes,
            cur_photos,
            cur_checked_in_by,
            cur_booking_kind_raw,
        )
        tg_reply_mid = int(cur_telegram_mid or 0)

    want_checkin = str(body.get("bookingKind") or body.get("booking_kind") or "").strip().lower() == "check_in"
    if want_checkin and cur_booking_kind == "bron" and "guestPassportSeries" not in body:
        return _json_error("Bronni check-in qilish uchun hujjat seriyasini yuboring", 400)

    next_check_in = body.get("checkInDate") or check_in_date
    next_nights = int(body["nights"]) if isinstance(body.get("nights"), int) else cur_nights
    converting_bron_to_checkin = want_checkin and cur_booking_kind == "bron"
    if body.get("checkInDate") is not None or body.get("nights") is not None:
        if body.get("checkInDate") is not None and not ISO_DATE.match(str(body["checkInDate"])):
            return _json_error("Kirish sanasi yyyy-mm-dd ko‘rinishida bo‘lishi kerak.", 400)
        if not converting_bron_to_checkin and _has_overlap(
            room_id, bed_index, str(next_check_in), int(next_nights), bid
        ):
            return _json_error(
                "Bu sanalar boshqa yozuv bilan ustma-ust. Kun yoki tunlar sonini o‘zgartiring.", 409
            )

    sets: list[str] = []
    vals: list[Any] = []
    patch_identity_warning: dict[str, Any] | None = None
    if "guestName" in body:
        sets.append("guest_name = %s")
        vals.append(str(body["guestName"])[:200])
    if "guestPhone" in body or "guestPassportSeries" in body:
        rp = str(body["guestPhone"]) if "guestPhone" in body else ""
        rpass = str(body["guestPassportSeries"]) if "guestPassportSeries" in body else ""
        with connection.cursor() as c2:
            if "guestPhone" not in body:
                if cur_guest_id:
                    c2.execute(
                        "SELECT phone_normalized FROM guests WHERE id = %s",
                        [int(cur_guest_id)],
                    )
                    rowp = c2.fetchone()
                    rp = str(rowp[0] or "") if rowp else normalize_phone_digits(cur_guest_phone)
                else:
                    rp = normalize_phone_digits(cur_guest_phone)
            if "guestPassportSeries" not in body:
                if cur_guest_id:
                    c2.execute(
                        "SELECT passport_series FROM guests WHERE id = %s",
                        [int(cur_guest_id)],
                    )
                    rowps = c2.fetchone()
                    rpass = str(rowps[0] or "") if rowps else ""
                elif len(normalize_phone_digits(cur_guest_phone)) < 9:
                    rpass = normalize_passport_series(cur_guest_phone)
        ik, id_err = compute_identity_key(rp, rpass)
        pn_try = normalize_phone_digits(rp)
        ps_try = normalize_passport_series(rpass)
        if id_err or not ik:
            if not (cur_guest_id is None and not pn_try and not ps_try):
                return _json_error(id_err or "Mehmon identifikatori noto‘g‘ri", 400)
        if ik is not None and cur_booking_kind == "bron":
            br_line = normalize_passport_series(rpass)
            if len(br_line) >= 4 and br_line.startswith("BRON"):
                return _json_error(
                    "Check-in uchun haqiqiy pasport yoki haydovchilik guvohnomasi seriyasini kiriting",
                    400,
                )
        if ik is None:
            pass
        else:
            d = identity_hostel_active_stay_overlap_detail(
                hostel_name, ik, str(next_check_in), int(next_nights), exclude_booking_id=bid
            )
            if d is not None:
                patch_identity_warning = d
            gn = str(body["guestName"])[:200] if "guestName" in body else cur_guest_name
            pn = normalize_phone_digits(rp)
            ps = normalize_passport_series(rpass)
            with connection.cursor() as c3:
                gid = upsert_guest(c3, ik, pn, ps, gn or "Mehmon")
                gp = guest_phone_column_value(ik, pn, ps)
            sets.append("guest_phone = %s")
            vals.append(gp)
            sets.append("guest_id = %s")
            vals.append(gid)
            if cur_booking_kind == "bron":
                sets.append("booking_kind = %s")
                vals.append("check_in")
                sets.append("expected_arrival = %s")
                vals.append("")
    if "price" in body:
        sets.append("price = %s")
        vals.append(_money_int_text(body["price"]))
    if "paid" in body:
        sets.append("paid = %s")
        vals.append(_money_int_text(body["paid"]))
    if "notes" in body:
        sets.append("notes = %s")
        vals.append(str(body["notes"])[:2000])
    if "nights" in body:
        sets.append("nights = %s")
        vals.append(int(body["nights"]))
    if "checkInDate" in body:
        sets.append("check_in_date = %s")
        vals.append(str(body["checkInDate"]))
    if "photos" in body and isinstance(body["photos"], list):
        sets.append("photos = %s")
        vals.append(json.dumps(body["photos"][:20]))
    if "checkedInBy" in body:
        sets.append("checked_in_by = %s")
        vals.append(str(body["checkedInBy"])[:120])
    if not sets:
        out: dict[str, Any] = {"ok": True, "updated": False}
        if patch_identity_warning is not None:
            out["identityOverlapWarning"] = patch_identity_warning
        return JsonResponse(out)
    sets.append("updated_at = CURRENT_TIMESTAMP")
    vals.append(bid)
    after_snap: dict[str, Any] | None = None
    with connection.cursor() as c:
        c.execute(f"UPDATE bed_bookings SET {', '.join(sets)} WHERE id = %s", vals)
        if "photos" in body and isinstance(body.get("photos"), list):
            c.execute("SELECT guest_id FROM bed_bookings WHERE id = %s", [bid])
            rr = c.fetchone()
            gid_for_doc = int(rr[0]) if rr and rr[0] else 0
            photos_body = body.get("photos") if isinstance(body.get("photos"), list) else []
            if gid_for_doc and photos_body:
                doc = parse_document_fields_from_photo(str(photos_body[0] or ""))
                if doc:
                    upsert_guest_document_fields(c, gid_for_doc, doc)
        if "guestName" in body:
            c.execute("SELECT guest_id FROM bed_bookings WHERE id = %s", [bid])
            gr = c.fetchone()
            if gr and gr[0]:
                c.execute(
                    """
                    UPDATE guests SET guest_name = %s, updated_at = CURRENT_TIMESTAMP
                    WHERE id = %s
                    """,
                    [str(body["guestName"])[:200], int(gr[0])],
                )
        c.execute(
            """
            SELECT check_in_date, nights, guest_name, guest_phone, price, paid, notes, photos, checked_in_by,
                   COALESCE(booking_kind, 'check_in')
            FROM bed_bookings
            WHERE id = %s
            """,
            [bid],
        )
        row_after = c.fetchone()
        if row_after:
            after_snap = _booking_telegram_snapshot_row(*row_after)
    resp: dict[str, Any] = {"ok": True, "updated": True}
    if patch_identity_warning is not None:
        resp["identityOverlapWarning"] = patch_identity_warning
    if after_snap is not None and before_snap and tg_reply_mid > 0:
        auth_req = _request_auth(request)
        who_html = ""
        if auth_req:
            wn = str(auth_req.get("display_name") or "").strip()
            if wn:
                who_html = f"👨‍💼 Kim: {_tg_html(wn)}"
        try:
            reply_html = _booking_channel_patch_reply_html(before_snap, after_snap, bid, who_html)
            if reply_html:
                _telegram_send_channel_html_reply(tg_reply_mid, reply_html)
        except Exception:
            logger.exception("Telegram kanal patch reply")
    return JsonResponse(resp)


def _bookings_delete(request, booking_id: uuid.UUID):
    bid = str(booking_id)
    raw = _read_json(request)
    reason_label = ""
    if isinstance(raw, dict):
        reason_label = str(raw.get("cancelReason", "")).strip()[:500]
    if not reason_label:
        return _json_error("cancelReason majburiy (bekor sababi)", 400)
    cancel_meta: dict[str, Any] | None = None
    with transaction.atomic():
        with connection.cursor() as c:
            c.execute(
                """
                SELECT h.name, r.code, COALESCE(r.name, r.code, ''),
                       b.bed_index, COALESCE(b.guest_name, ''), COALESCE(b.booking_kind, 'check_in')
                FROM bed_bookings b
                JOIN rooms r ON r.id = b.room_id
                JOIN hostels h ON h.id = r.hostel_id
                WHERE b.id = %s AND b.status = 'active'
                """,
                [bid],
            )
            row = c.fetchone()
            if not row:
                return _json_error("Faol yozuv topilmadi.", 404)
            hostel_name = str(row[0] or "")
            room_code = str(row[1] or "")
            room_name = str(row[2] or "")
            bed_index = int(row[3] or 0)
            guest_name = str(row[4] or "")
            booking_kind = str(row[5] or "check_in").strip().lower()
            is_bron = booking_kind == "bron"
            cancel_meta = {
                "hostel": hostel_name,
                "room_code": room_code,
                "room_name": room_name,
                "bed_index": bed_index,
                "guest_name": guest_name,
                "booking_kind": booking_kind,
            }
            c.execute(
                """
                UPDATE bed_bookings
                SET status = 'cancelled',
                    cancel_reason_bron = CASE WHEN %s = 1 THEN %s ELSE cancel_reason_bron END,
                    cancel_reason_checkin = CASE WHEN %s = 1 THEN cancel_reason_checkin ELSE %s END,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = %s AND status = 'active'
                """,
                [1 if is_bron else 0, reason_label, 1 if is_bron else 0, reason_label, bid],
            )
            if c.rowcount == 0:
                return _json_error("Faol yozuv topilmadi.", 404)
    if cancel_meta:
        try:
            _notify_booking_channel_cancelled(
                hostel=cancel_meta["hostel"],
                room_code=cancel_meta["room_code"],
                room_name=cancel_meta["room_name"],
                bed_index=int(cancel_meta["bed_index"]),
                guest_name=cancel_meta["guest_name"],
                booking_kind=str(cancel_meta["booking_kind"]),
                reason=reason_label,
                booking_id=bid,
            )
        except Exception:
            logger.exception("Telegram kanal bildirishnomasi (cancel) ishlamadi")
    return JsonResponse({"ok": True})


@csrf_exempt
@require_http_methods(["PATCH", "DELETE"])
def booking_detail(request, booking_id: uuid.UUID):
    if request.method == "PATCH":
        return _bookings_patch(request, booking_id)
    return _bookings_delete(request, booking_id)


@csrf_exempt
@require_http_methods(["GET"])
def guests_recent(request):
    try:
        limit = min(int(request.GET.get("limit") or 40), 200)
    except ValueError:
        limit = 40
    with connection.cursor() as c:
        ensure_guest_schema(c)
        c.execute(
            """
            SELECT
              latest.lk,
              latest.guest_name,
              latest.check_in_date,
              CAST(latest.price AS TEXT),
              CAST(latest.paid AS TEXT),
              latest.notes,
              latest.hostel,
              latest.room_name,
              COALESCE(
                NULLIF(latest.g_phone, ''),
                CASE WHEN latest.lk LIKE 'phone:%%' THEN substr(latest.lk, 7) ELSE '' END
              ) AS out_phone,
              COALESCE(
                NULLIF(latest.g_pass, ''),
                CASE WHEN latest.lk LIKE 'doc:%%' THEN substr(latest.lk, 5)
                     WHEN latest.lk LIKE 'passport:%%' THEN substr(latest.lk, 10)
                     ELSE '' END
              ) AS out_pass,
              latest.nights,
              latest.booking_photos
            FROM (
              SELECT
                COALESCE(
                  g.identity_key,
                  CASE
                    WHEN length(regexp_replace(COALESCE(b.guest_phone, ''), '[^0-9]', '', 'g')) >= 9
                    THEN 'phone:' || trim(regexp_replace(COALESCE(b.guest_phone, ''), '[^0-9]', '', 'g'))
                    ELSE 'doc:' || upper(trim(COALESCE(b.guest_phone, '')))
                  END
                ) AS lk,
                b.guest_name,
                b.check_in_date,
                b.price,
                b.paid,
                b.nights AS nights,
                b.notes,
                h.name AS hostel,
                r.name AS room_name,
                COALESCE(g.phone_normalized, '') AS g_phone,
                COALESCE(g.passport_series, '') AS g_pass,
                COALESCE(b.photos, '[]') AS booking_photos,
                ROW_NUMBER() OVER (
                  PARTITION BY COALESCE(
                    g.identity_key,
                    CASE
                      WHEN length(regexp_replace(COALESCE(b.guest_phone, ''), '[^0-9]', '', 'g')) >= 9
                      THEN 'phone:' || trim(regexp_replace(COALESCE(b.guest_phone, ''), '[^0-9]', '', 'g'))
                      ELSE 'doc:' || upper(trim(COALESCE(b.guest_phone, '')))
                    END
                  )
                  ORDER BY b.check_in_date DESC, b.created_at DESC
                ) AS rn
              FROM bed_bookings b
              JOIN rooms r ON r.id = b.room_id
              JOIN hostels h ON h.id = r.hostel_id
              LEFT JOIN guests g ON g.id = b.guest_id
              WHERE b.status IN ('active', 'cancelled')
            ) latest
            WHERE latest.rn = 1
            ORDER BY latest.check_in_date DESC
            LIMIT %s
            """,
            [limit],
        )
        guests = []
        for r in c.fetchall():
            photos_raw = r[11]
            if isinstance(photos_raw, list):
                photos = photos_raw
            elif isinstance(photos_raw, str):
                try:
                    j = json.loads(photos_raw)
                    photos = j if isinstance(j, list) else []
                except json.JSONDecodeError:
                    photos = []
            else:
                photos = []
            photos_out = [str(u) for u in photos if isinstance(u, str) and u.strip()][:3]
            guests.append(
                {
                    "lookupKey": r[0] or "",
                    "name": r[1] or "",
                    "phone": r[8] or "",
                    "passportSeries": r[9] or "",
                    "lastVisit": r[2] or "",
                    "price": int(_money_int_text(r[3])),
                    "paid": int(_money_int_text(r[4])),
                    "notes": (r[5] or "") or None,
                    "hostel": r[6],
                    "room": r[7],
                    "nights": max(1, min(365, int(r[10] or 1))),
                    "photos": photos_out,
                }
            )
    return JsonResponse({"guests": guests})


@csrf_exempt
@require_http_methods(["GET"])
def guests_history(request):
    lk = str(request.GET.get("lookupKey") or "").strip().lower()
    if not lk:
        return _json_error("lookupKey required", 400)
    if not (lk.startswith("phone:") or lk.startswith("doc:") or lk.startswith("passport:")):
        return _json_error("lookupKey invalid", 400)
    with connection.cursor() as c:
        c.execute(
            """
            WITH entries AS (
              SELECT
                CAST(b.id AS TEXT) AS booking_id,
                r.name AS room_name,
                h.name AS hostel_name,
                b.bed_index,
                b.check_in_date,
                b.nights,
                COALESCE(b.booking_kind, 'check_in') AS booking_kind,
                COALESCE(b.status, 'active') AS status,
                COALESCE(b.notes, '') AS notes,
                COALESCE(b.cancel_reason_bron, '') AS cancel_reason_bron,
                COALESCE(b.cancel_reason_checkin, '') AS cancel_reason_checkin,
                CAST(COALESCE(b.price, 0) AS TEXT) AS price,
                CAST(COALESCE(b.paid, 0) AS TEXT) AS paid,
                COALESCE(b.guest_name, '') AS guest_name,
                COALESCE(b.created_at, '') AS created_at,
                COALESCE(b.updated_at, '') AS updated_at,
                (
                  CASE
                    WHEN length(regexp_replace(COALESCE(b.guest_phone, ''), '[^0-9]', '', 'g')) >= 9
                    THEN 'phone:' || trim(regexp_replace(COALESCE(b.guest_phone, ''), '[^0-9]', '', 'g'))
                    ELSE 'doc:' || upper(trim(COALESCE(b.guest_phone, '')))
                  END
                ) AS lookup_key
              FROM bed_bookings b
              JOIN rooms r ON r.id = b.room_id
              JOIN hostels h ON h.id = r.hostel_id
              WHERE b.status IN ('active', 'cancelled')
            )
            SELECT booking_id, room_name, hostel_name, bed_index, check_in_date, nights, booking_kind, status,
                   notes, cancel_reason_bron, cancel_reason_checkin, price, paid, guest_name, created_at, updated_at
            FROM entries
            WHERE lower(lookup_key) = %s
            ORDER BY check_in_date DESC, created_at DESC
            LIMIT 200
            """,
            [lk],
        )
        rows = c.fetchall()
    history = []
    for r in rows:
        booking_kind = str(r[6] or "check_in").strip().lower()
        status = str(r[7] or "active").strip().lower()
        if status == "active":
            event = "check_in" if booking_kind == "check_in" else "bron"
        else:
            event = "check_out" if booking_kind == "check_in" else "bron_cancel"
        history.append(
            {
                "bookingId": str(r[0] or ""),
                "roomName": str(r[1] or ""),
                "hostel": str(r[2] or ""),
                "bedIndex": int(r[3] or 0),
                "checkInDate": str(r[4] or ""),
                "nights": int(r[5] or 1),
                "bookingKind": "bron" if booking_kind == "bron" else "check_in",
                "status": "cancelled" if status == "cancelled" else "active",
                "eventType": event,
                "notes": str(r[8] or ""),
                "cancelReasonBron": str(r[9] or ""),
                "cancelReasonCheckin": str(r[10] or ""),
                "price": _money_int_text(r[11]),
                "paid": _money_int_text(r[12]),
                "guestName": str(r[13] or ""),
                "createdAt": str(r[14] or ""),
                "updatedAt": str(r[15] or ""),
            }
        )
    return JsonResponse({"history": history})


@csrf_exempt
@require_http_methods(["GET"])
def cleaning_list(request):
    hostel = request.GET.get("hostel") or "Vodnik"
    d = request.GET.get("date") or ""
    date_iso = d if ISO_DATE.match(d) else _today_iso()

    with connection.cursor() as c:
        _prune_old_cleaning_photos(c)
        c.execute(
            """
            SELECT
              r.code,
              r.name,
              r.bed_count,
              r.room_kind,
              rc.status,
              COALESCE(CAST(rc.full_taken AS integer), 0),
              COALESCE(rc.full_taken_mode, ''),
              rc.photos_before,
              rc.photos_after,
              (
                SELECT CAST(COUNT(*) AS TEXT) FROM bed_bookings b
                WHERE b.room_id = r.id AND b.status = 'active'
                  AND CAST(NULLIF(b.check_in_date, '') AS date) <= CAST(%s AS date)
                  AND CAST(%s AS date) < (CAST(NULLIF(b.check_in_date, '') AS date) + (COALESCE(b.nights, 1) * INTERVAL '1 day'))
              ) AS occupied,
              (
                SELECT b.guest_name FROM bed_bookings b
                WHERE b.room_id = r.id AND b.status = 'active'
                  AND CAST(NULLIF(b.check_in_date, '') AS date) <= CAST(%s AS date)
                  AND CAST(%s AS date) < (CAST(NULLIF(b.check_in_date, '') AS date) + (COALESCE(b.nights, 1) * INTERVAL '1 day'))
                ORDER BY b.bed_index ASC
                LIMIT 1
              ) AS guest_name
            FROM rooms r
            JOIN hostels h ON h.id = r.hostel_id
            LEFT JOIN room_cleaning rc ON rc.room_id = r.id
            WHERE h.name = %s
            ORDER BY r.room_kind DESC, r.id
            """,
            [date_iso, date_iso, date_iso, date_iso, hostel],
        )
        rooms = []
        for row in c.fetchall():
            pb, pa = row[7], row[8]

            def _jarr(v: Any) -> list:
                if isinstance(v, list):
                    return v
                if isinstance(v, str):
                    try:
                        j = json.loads(v)
                        return j if isinstance(j, list) else []
                    except json.JSONDecodeError:
                        return []
                return []

            rooms.append(
                {
                    "id": row[0],
                    "name": row[1],
                    "hostel": hostel,
                    "guestName": row[9] or "",
                    "status": "cleaned" if (row[4] or "dirty") == "cleaned" else "dirty",
                    "fullTaken": bool(int(row[5] or 0)),
                    "fullTakenMode": str(row[6] or ""),
                    "type": "bathroom" if row[3] == "bathroom" else "room",
                    "totalBeds": row[2],
                    "occupiedBeds": int(row[9] or 0),
                    "photosBefore": _jarr(pb),
                    "photosAfter": _jarr(pa),
                }
            )
    return JsonResponse({"hostel": hostel, "date": date_iso, "rooms": rooms})


@csrf_exempt
@require_http_methods(["PATCH"])
def cleaning_patch(request, room_code: str):
    body = _read_json(request)
    if body is None:
        return _json_error("Invalid JSON")
    hostel = body.get("hostel") or ""
    if not hostel:
        return _json_error("hostel required", 400)
    room = _resolve_room(hostel, room_code)
    if not room:
        return _json_error("Room not found", 404)
    room_id = int(room["id"])
    sets: list[str] = []
    vals: list[Any] = []
    if "status" in body:
        st = body.get("status")
        if st not in ("dirty", "cleaned"):
            return _json_error("Invalid status", 400)
        sets.append("status = %s")
        vals.append(st)
    if "photosBefore" in body and isinstance(body.get("photosBefore"), list):
        sets.append("photos_before = %s")
        vals.append(json.dumps(body["photosBefore"][:20]))
    if "photosAfter" in body and isinstance(body.get("photosAfter"), list):
        sets.append("photos_after = %s")
        vals.append(json.dumps(body["photosAfter"][:20]))
    if "fullTaken" in body:
        sets.append("full_taken = %s")
        vals.append(1 if bool(body.get("fullTaken")) else 0)
        if not bool(body.get("fullTaken")):
            sets.append("full_taken_mode = %s")
            vals.append("")
    if "fullTakenMode" in body:
        mode = str(body.get("fullTakenMode") or "").strip().lower()
        if mode not in ("", "check_in", "bron"):
            return _json_error("Invalid fullTakenMode", 400)
        sets.append("full_taken_mode = %s")
        vals.append(mode)
    if not sets:
        return JsonResponse({"ok": True, "updated": False})
    sets.append("updated_at = CURRENT_TIMESTAMP")
    vals.append(room_id)
    with connection.cursor() as c:
        _prune_old_cleaning_photos(c)
        # Some deployments may miss a `room_cleaning` row for newly seeded/added rooms.
        # Ensure row exists so fullTaken/fullTakenMode updates are never silently ignored.
        c.execute(
            """
            INSERT INTO room_cleaning
              (room_id, status, full_taken, full_taken_mode, photos_before, photos_after, updated_at)
            VALUES
              (%s, 'dirty', FALSE, '', '[]', '[]', CURRENT_TIMESTAMP)
            ON CONFLICT (room_id) DO NOTHING
            """,
            [room_id],
        )
        c.execute(f"UPDATE room_cleaning SET {', '.join(sets)} WHERE room_id = %s", vals)
    return JsonResponse({"ok": True, "updated": True})
