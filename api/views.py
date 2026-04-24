from __future__ import annotations

import json
import re
import uuid
from datetime import date
from typing import Any

import bcrypt
from django.db import connection, transaction
from django.db.utils import IntegrityError
from django.http import JsonResponse
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
            SELECT r.code, rc.status, COALESCE(rc.full_taken, 0), COALESCE(rc.full_taken_mode, '')
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
    if request.method in ("GET", "HEAD"):
        with connection.cursor() as c:
            c.execute(
                """
                SELECT id, login, display_name, role, active, created_at
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
            c.execute(
                "INSERT INTO users (login, display_name, password_hash, role) VALUES (%s, %s, %s, %s) RETURNING id",
                [login_l, display_name, pw_hash, role],
            )
            new_id = c.fetchone()[0]
    except IntegrityError:
        return _json_error("Bu login allaqachon mavjud", 409)
    return JsonResponse({"id": new_id, "login": login_l}, status=201)


def _users_patch(request, user_id: int):
    body = _read_json(request)
    if body is None:
        return _json_error("Invalid JSON")
    sets: list[str] = []
    vals: list[Any] = []
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
        if role not in ("admin", "staff"):
            return _json_error("Invalid role", 400)
        sets.append("role = %s")
        vals.append(role)
    if "active" in body:
        sets.append("active = %s")
        vals.append(1 if body.get("active") else 0)
    if not sets:
        return JsonResponse({"ok": True, "updated": False})
    vals.append(user_id)
    with connection.cursor() as c:
        c.execute(f"UPDATE users SET {', '.join(sets)} WHERE id = %s", vals)
        if c.rowcount == 0:
            return _json_error("Foydalanuvchi topilmadi", 404)
    return JsonResponse({"ok": True, "updated": True})


def _users_delete(_request, user_id: int):
    with connection.cursor() as c:
        c.execute("UPDATE users SET active = 0 WHERE id = %s AND active = 1", [user_id])
        if c.rowcount == 0:
            return _json_error("Faol foydalanuvchi topilmadi", 404)
    return JsonResponse({"ok": True})


@csrf_exempt
@require_http_methods(["PATCH", "DELETE"])
def user_detail(request, user_id: int):
    if request.method == "PATCH":
        return _users_patch(request, user_id)
    return _users_delete(request, user_id)


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
    checked_in_by = body.get("checkedInBy") or ""
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
    return JsonResponse(
        {"ids": inserted, "identityOverlapWarnings": identity_overlap_warnings},
        status=201,
    )


def _bookings_patch(request, booking_id: uuid.UUID):
    body = _read_json(request)
    if body is None:
        return _json_error("Maʼlumot formati buzilgan (JSON).")
    bid = str(booking_id)
    with connection.cursor() as c:
        ensure_guest_schema(c)
        c.execute(
            """
            SELECT b.room_id, b.bed_index, b.check_in_date, b.nights, b.guest_name, b.guest_phone,
                   b.guest_id, h.name, COALESCE(b.booking_kind, 'check_in')
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
        )
        cur_booking_kind = "bron" if str(cur_booking_kind_raw or "").strip().lower() == "bron" else "check_in"

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
    resp: dict[str, Any] = {"ok": True, "updated": True}
    if patch_identity_warning is not None:
        resp["identityOverlapWarning"] = patch_identity_warning
    return JsonResponse(resp)


def _bookings_delete(request, booking_id: uuid.UUID):
    bid = str(booking_id)
    raw = _read_json(request)
    reason_label = ""
    if isinstance(raw, dict):
        reason_label = str(raw.get("cancelReason", "")).strip()[:500]
    if not reason_label:
        return _json_error("cancelReason majburiy (bekor sababi)", 400)
    with transaction.atomic():
        with connection.cursor() as c:
            c.execute(
                "SELECT COALESCE(booking_kind, 'check_in') FROM bed_bookings WHERE id = %s AND status = 'active'",
                [bid],
            )
            row = c.fetchone()
            if not row:
                return _json_error("Faol yozuv topilmadi.", 404)
            booking_kind = str(row[0] or "check_in").strip().lower()
            is_bron = booking_kind == "bron"
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
              COALESCE(rc.full_taken, 0),
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
        c.execute(f"UPDATE room_cleaning SET {', '.join(sets)} WHERE room_id = %s", vals)
    return JsonResponse({"ok": True, "updated": True})
