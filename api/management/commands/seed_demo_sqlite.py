"""SQLite faylini qayta yaratadi: sql/schema.sql + demo xonalar va bronlar (faqat ENGINE=sqlite3)."""

from __future__ import annotations

import sqlite3
import uuid
from datetime import date
from pathlib import Path

import bcrypt
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

# (hostel, code, name, bed_count, room_kind)
ROOMS: list[tuple[str, str, str, int, str]] = [
    ("Vodnik", "v1", "1-qavat Zal", 4, "dorm"),
    ("Vodnik", "v2", "1-qavat Lux", 2, "dorm"),
    ("Vodnik", "v3", "1-qavat Koridor", 2, "dorm"),
    ("Vodnik", "v4", "2-qavat Zal", 4, "dorm"),
    ("Vodnik", "v5", "2-qavat Dvuxspalniy", 2, "dorm"),
    ("Vodnik", "v6", "2-qavat 2 Kishilik", 2, "dorm"),
    ("Vodnik", "v7", "2-qavat Koridor", 1, "dorm"),
    ("Vodnik", "v-bath", "Umumiy dush va hojatxona", 0, "bathroom"),
    ("Zargarlik", "z1", "1-xona 7 TA krovat", 7, "dorm"),
    ("Zargarlik", "z2", "2-xona 3 TA krovat", 3, "dorm"),
    ("Zargarlik", "z3", "3-xona 3 TA krovat", 3, "dorm"),
    ("Zargarlik", "z4", "4-xona 3 TA krovat", 3, "dorm"),
    ("Zargarlik", "z-bath", "Umumiy dush va hojatxona", 0, "bathroom"),
    ("Tabarruk", "t1", "1-xona Dushli", 2, "dorm"),
    ("Tabarruk", "t2", "2-xona Dushli", 2, "dorm"),
    ("Tabarruk", "t3", "3-xona", 2, "dorm"),
    ("Tabarruk", "t4", "4-xona", 2, "dorm"),
    ("Tabarruk", "t5", "5-xona", 2, "dorm"),
    ("Tabarruk", "t6", "6-xona", 2, "dorm"),
    ("Tabarruk", "t7", "7-xona", 2, "dorm"),
    ("Tabarruk", "t8", "8-xona", 2, "dorm"),
    ("Tabarruk", "t-bath", "Umumiy dush va hojatxona", 0, "bathroom"),
]

# (hostel, code, bed_index, guest_name, guest_phone, price, paid, notes, checked_in_by)
BOOKINGS: list[tuple[str, str, int, str, str, str, str, str, str]] = [
    ("Vodnik", "v1", 3, "Miroj", "998901234567", "80000", "80000", "oilali", "Doston"),
    ("Vodnik", "v1", 4, "Akbar", "998911234567", "75000", "75000", "", "Doston"),
    ("Vodnik", "v2", 1, "Fatima", "998921234567", "90000", "90000", "", "Sardor"),
    ("Vodnik", "v4", 1, "Sherzod", "998931234567", "70000", "70000", "", "Doston"),
    ("Vodnik", "v4", 2, "Gulnora", "998941234567", "70000", "70000", "", "Doston"),
    ("Vodnik", "v5", 1, "Alisher", "998951234567", "120000", "120000", "juftlik", "Sardor"),
    ("Vodnik", "v5", 2, "Nodira", "998961234567", "120000", "120000", "", "Sardor"),
    ("Vodnik", "v7", 1, "Rustam", "998971234567", "50000", "50000", "", "Doston"),
    ("Zargarlik", "z1", 1, "Javohir", "998981234567", "65000", "65000", "", "Sardor"),
    ("Zargarlik", "z1", 2, "Sevara", "998991234567", "65000", "65000", "", "Sardor"),
    ("Zargarlik", "z3", 1, "Hamid", "998901111111", "60000", "60000", "", "Doston"),
    ("Zargarlik", "z3", 2, "Zainab", "998902222222", "60000", "60000", "", "Doston"),
    ("Zargarlik", "z3", 3, "Karim", "998903333333", "60000", "60000", "", "Sardor"),
    ("Zargarlik", "z4", 2, "Timur", "998905555555", "85000", "85000", "", "Doston"),
    ("Tabarruk", "t1", 1, "Aziz", "998906666666", "100000", "100000", "", "Sardor"),
    ("Tabarruk", "t3", 1, "Bahor", "998907777777", "85000", "85000", "", "Doston"),
    ("Tabarruk", "t5", 1, "Daler", "998908888888", "85000", "85000", "", "Sardor"),
    ("Tabarruk", "t5", 2, "Elina", "998909999999", "85000", "85000", "", "Sardor"),
    ("Tabarruk", "t7", 2, "Farkhod", "998910101010", "70000", "70000", "", "Doston"),
    ("Tabarruk", "t8", 1, "Gulzira", "998911111111", "75000", "75000", "", "Sardor"),
]


class Command(BaseCommand):
    help = "SQLite biznes bazasini schema.sql bo'yicha qayta yaratadi va demo ma'lumot qo'yadi."

    def handle(self, *args, **options):
        eng = settings.DATABASES["default"]["ENGINE"]
        if "sqlite" not in eng:
            raise CommandError("Bu buyruq faqat SQLite uchun (DATABASE_URL Postgres bo'lmasin).")

        db_path = Path(settings.DATABASES["default"]["NAME"])
        db_path.parent.mkdir(parents=True, exist_ok=True)

        schema_file = Path(settings.BASE_DIR) / "sql" / "schema.sql"
        if not schema_file.is_file():
            raise CommandError(f"schema.sql topilmadi: {schema_file}")

        sql = schema_file.read_text(encoding="utf-8")

        conn = sqlite3.connect(str(db_path))
        try:
            conn.executescript(sql)
            cur = conn.cursor()

            cur.executemany(
                "INSERT INTO hostels (name) VALUES (?)",
                [("Vodnik",), ("Zargarlik",), ("Tabarruk",)],
            )
            cur.execute("SELECT id, name FROM hostels")
            hostel_ids = {name: hid for hid, name in cur.fetchall()}

            room_ids: dict[str, int] = {}
            for hostel, code, name, bed_count, room_kind in ROOMS:
                hid = hostel_ids.get(hostel)
                if hid is None:
                    continue
                cur.execute(
                    """
                    INSERT INTO rooms (hostel_id, code, name, bed_count, room_kind)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (hid, code, name, bed_count, room_kind),
                )
                room_ids[f"{hostel}:{code}"] = int(cur.lastrowid)

            for rid in room_ids.values():
                cur.execute(
                    """
                    INSERT OR IGNORE INTO room_cleaning (room_id, status, photos_before, photos_after)
                    VALUES (?, 'dirty', '[]', '[]')
                    """,
                    (rid,),
                )

            check_in = date.today().isoformat()
            nights = 30
            for hostel, code, bed_index, guest_name, guest_phone, price, paid, notes, checked_in_by in BOOKINGS:
                key = f"{hostel}:{code}"
                room_id = room_ids.get(key)
                if room_id is None:
                    continue
                cur.execute(
                    """
                    INSERT INTO bed_bookings (
                      id, room_id, bed_index, check_in_date, nights, guest_name, guest_phone,
                      price, paid, notes, photos, checked_in_by, status
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '[]', ?, 'active')
                    """,
                    (
                        str(uuid.uuid4()),
                        room_id,
                        bed_index,
                        check_in,
                        nights,
                        guest_name,
                        guest_phone,
                        float(price),
                        float(paid),
                        notes,
                        checked_in_by,
                    ),
                )

            demo_hash = bcrypt.hashpw(b"demo123", bcrypt.gensalt(rounds=10)).decode("ascii")
            cur.execute(
                """
                INSERT INTO users (login, display_name, password_hash, role) VALUES
                ('doston', 'Doston', ?, 'admin'),
                ('sardor', 'Sardor', ?, 'staff')
                """,
                (demo_hash, demo_hash),
            )

            conn.commit()
        finally:
            conn.close()

        self.stdout.write(self.style.SUCCESS(f"SQLite tayyor: {db_path}"))
