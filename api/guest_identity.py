"""Mehmon identifikatori: telefon yoki pasport seriyasi; SQLite `guests` sxemasi."""

from __future__ import annotations

import re
from typing import Any

from django.db import connection


def normalize_passport_series(raw: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", (raw or "").upper())[:64]


def normalize_phone_digits(raw: str) -> str:
    return re.sub(r"\D", "", raw or "")


def compute_identity_key(phone: str, passport_series: str) -> tuple[str | None, str | None]:
    """
    Birlamchi identifikator: HUJJAT seriyasi (pasport yoki haydovchilik guvohnomasi, >=4 belgi).
    Telefon — ixtiyoriy qo‘shimcha, unique uchun ishlatilmaydi.
    Eski yozuvlar uchun: agar seriya bo‘lmasa va telefon (>=9 raqam) bo‘lsa — `phone:` kalitiga tushadi.
    Qaytaradi: (identity_key, xato_xabari).
    """
    ps = normalize_passport_series(passport_series)
    pn = normalize_phone_digits(phone)
    if len(ps) >= 4:
        return f"doc:{ps}", None
    if len(pn) >= 9:
        return f"phone:{pn}", None
    return None, "Hujjat seriyasi (pasport yoki haydovchilik guvohnomasi, kamida 4 belgi) kerak"


def guest_phone_column_value(identity_key: str, phone_norm: str, passport_norm: str) -> str:
    """`bed_bookings.guest_phone` — taxtada ko‘rinadi (hujjat seriyasi yoki telefon)."""
    if identity_key.startswith("doc:") or identity_key.startswith("passport:"):
        return (passport_norm or phone_norm)[:32]
    return (phone_norm or passport_norm)[:32]


def ensure_guest_schema(cursor) -> None:
    """Idempotent: `guests` jadvali va `bed_bookings.guest_id`."""
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='guests'")
    if not cursor.fetchone():
        cursor.execute(
            """
            CREATE TABLE guests (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              identity_key TEXT NOT NULL UNIQUE,
              phone_normalized TEXT NOT NULL DEFAULT '',
              passport_series TEXT NOT NULL DEFAULT '',
              guest_name TEXT NOT NULL DEFAULT '',
              created_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP),
              updated_at TEXT NOT NULL DEFAULT (CURRENT_TIMESTAMP)
            )
            """
        )
        cursor.execute("CREATE INDEX IF NOT EXISTS guests_identity_idx ON guests(identity_key)")
    else:
        cursor.execute("CREATE INDEX IF NOT EXISTS guests_identity_idx ON guests(identity_key)")

    cursor.execute("PRAGMA table_info(bed_bookings)")
    cols = {row[1] for row in cursor.fetchall()}
    if "guest_id" not in cols:
        cursor.execute(
            """
            ALTER TABLE bed_bookings ADD COLUMN guest_id INTEGER REFERENCES guests(id)
            """
        )


def upsert_guest(
    cursor,
    identity_key: str,
    phone_norm: str,
    passport_norm: str,
    guest_name: str,
) -> int:
    """Mehmonni yaratadi yoki yangilaydi; `id` qaytaradi."""
    nm = (guest_name or "").strip()[:200]
    cursor.execute("SELECT id, guest_name FROM guests WHERE identity_key = %s", [identity_key])
    row = cursor.fetchone()
    if row:
        gid = int(row[0])
        old_nm = str(row[1] or "").strip()
        if nm and (not old_nm or len(nm) > len(old_nm)):
            cursor.execute(
                """
                UPDATE guests SET guest_name = %s,
                  phone_normalized = CASE WHEN %s <> '' THEN %s ELSE phone_normalized END,
                  passport_series = CASE WHEN %s <> '' THEN %s ELSE passport_series END,
                  updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                [nm, phone_norm, phone_norm, passport_norm, passport_norm, gid],
            )
        elif phone_norm or passport_norm:
            cursor.execute(
                """
                UPDATE guests SET
                  phone_normalized = CASE WHEN %s <> '' THEN %s ELSE phone_normalized END,
                  passport_series = CASE WHEN %s <> '' THEN %s ELSE passport_series END,
                  updated_at = CURRENT_TIMESTAMP
                WHERE id = %s
                """,
                [phone_norm, phone_norm, passport_norm, passport_norm, gid],
            )
        return gid

    cursor.execute(
        """
        INSERT INTO guests (identity_key, phone_normalized, passport_series, guest_name)
        VALUES (%s, %s, %s, %s)
        """,
        [identity_key, phone_norm[:32], passport_norm[:64], nm or "Mehmon"],
    )
    return int(cursor.lastrowid)


def identity_hostel_active_stay_overlap(
    hostel_name: str,
    identity_key: str,
    check_in: str,
    nights: int,
    exclude_booking_id: str | None = None,
) -> bool:
    """Shu identifikator bilan filialda aktiv bron sanalari kesishadimi.

    Eski yozuvlar `guests` jadvalisiz bo‘lsa: `bed_bookings.guest_phone` ustuniga
    qarab ham tekshiramiz (telefon raqami yoki hujjat seriyasi shu yerda saqlanadi).
    """
    legacy_value: str | None = None
    if identity_key.startswith("phone:"):
        legacy_value = identity_key[6:]
    elif identity_key.startswith("doc:"):
        legacy_value = identity_key[4:]
    elif identity_key.startswith("passport:"):
        legacy_value = identity_key[9:]
    with connection.cursor() as c:
        c.execute(
            """
            SELECT 1
            FROM bed_bookings b
            JOIN rooms r ON r.id = b.room_id
            JOIN hostels h ON h.id = r.hostel_id
            LEFT JOIN guests g ON g.id = b.guest_id
            WHERE h.name = %s AND b.status = 'active'
              AND (%s IS NULL OR CAST(b.id AS TEXT) <> %s)
              AND (
                (b.guest_id IS NOT NULL AND g.identity_key = %s)
                OR (b.guest_id IS NULL AND %s IS NOT NULL AND b.guest_phone = %s)
              )
              AND julianday(b.check_in_date) <= julianday(%s, '+' || (%s - 1) || ' days')
              AND julianday(%s) <= julianday(b.check_in_date, '+' || (b.nights - 1) || ' days')
            LIMIT 1
            """,
            [
                hostel_name,
                exclude_booking_id,
                exclude_booking_id,
                identity_key,
                legacy_value,
                legacy_value,
                check_in,
                nights,
                check_in,
            ],
        )
        return c.fetchone() is not None


def guest_latest_name_by_identity(identity_key: str) -> str:
    with connection.cursor() as c:
        c.execute("SELECT guest_name FROM guests WHERE identity_key = %s LIMIT 1", [identity_key])
        row = c.fetchone()
        if row and str(row[0] or "").strip():
            return str(row[0]).strip()[:200]
    legacy_value: str | None = None
    if identity_key.startswith("phone:"):
        legacy_value = identity_key[6:]
    elif identity_key.startswith("doc:"):
        legacy_value = identity_key[4:]
    elif identity_key.startswith("passport:"):
        legacy_value = identity_key[9:]
    if legacy_value:
        with connection.cursor() as c2:
            c2.execute(
                """
                SELECT guest_name FROM bed_bookings
                WHERE guest_phone = %s AND guest_id IS NULL
                ORDER BY check_in_date DESC, created_at DESC LIMIT 1
                """,
                [legacy_value],
            )
            row2 = c2.fetchone()
            if row2 and row2[0]:
                return str(row2[0]).strip()[:200]
    return ""


def resolve_guest_name_for_line(
    line: dict[str, Any],
    identity_key: str,
    phone_digits: str,
) -> str:
    g = str(line.get("guestName") or "").strip()[:200]
    if g:
        return g
    notes = str(line.get("notes") or "")
    m = re.match(r"^Mijoz:\s*(.+?)(?:\n|$)", notes.strip(), flags=re.I | re.S)
    if m:
        return m.group(1).strip()[:200]
    prev = guest_latest_name_by_identity(identity_key)
    if prev:
        return prev[:200]
    if len(phone_digits) >= 9:
        with connection.cursor() as c:
            c.execute(
                """
                SELECT guest_name FROM bed_bookings
                WHERE guest_phone = %s
                ORDER BY check_in_date DESC, created_at DESC LIMIT 1
                """,
                [phone_digits],
            )
            row = c.fetchone()
            if row and row[0]:
                return str(row[0]).strip()[:200]
    return "Mehmon"
