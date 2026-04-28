"""Hostellar va xonalar — GET /api/catalog/rooms bilan mos (idempotent)."""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import connection, transaction

# (hostel_name, room_code, display_name, bed_count, inactive) — katalog API bilan mos
ROOM_SEED: list[tuple[str, str, str, int, bool]] = [
    ("Vodnik", "v1", "1-qavat Zal", 4, False),
    ("Vodnik", "v2", "1-qavat Lux", 2, False),
    ("Vodnik", "v3", "1-qavat Koridor", 2, False),
    ("Vodnik", "v4", "2-qavat Zal", 4, False),
    ("Vodnik", "v5", "2-qavat Dvuxspalniy", 2, False),
    ("Vodnik", "v6", "2-qavat 2 Kishilik", 2, False),
    ("Vodnik", "v7", "2-qavat Koridor", 1, False),
    ("Zargarlik", "z1", "1-xona 7 ta krovat", 7, False),
    ("Zargarlik", "z2", "2-xona 3 ta krovat", 3, False),
    ("Zargarlik", "z3", "3-xona 1 ta krovat", 1, True),
    ("Zargarlik", "z4", "4-xona 3 ta krovat", 3, False),
    ("Tabarruk", "t1", "1-xona Dushli", 3, False),
    ("Tabarruk", "t2", "2-xona Dushli", 2, False),
    ("Tabarruk", "t3", "3-xona", 2, False),
    ("Tabarruk", "t4", "4-xona", 2, False),
    ("Tabarruk", "t5", "5-xona", 2, False),
    ("Tabarruk", "t6", "6-xona", 2, False),
    ("Tabarruk", "t7", "7-xona", 2, False),
]

HOSTELS = ("Vodnik", "Zargarlik", "Tabarruk")


class Command(BaseCommand):
    help = "Hostels + rooms jadvalini static frontend bilan mos qilib to'ldiradi (takrorlash xavfsiz)."

    def handle(self, *args, **options):
        with transaction.atomic():
            with connection.cursor() as c:
                for name in HOSTELS:
                    c.execute(
                        "INSERT INTO hostels (name) VALUES (%s) ON CONFLICT (name) DO NOTHING",
                        [name],
                    )

                for hostel_name, code, rname, beds, inactive in ROOM_SEED:
                    c.execute(
                        """
                        INSERT INTO rooms (hostel_id, code, name, bed_count, room_kind, photos, inactive)
                        SELECT h.id, %s, %s, %s, 'dorm', '[]', %s
                        FROM hostels h
                        WHERE h.name = %s
                        ON CONFLICT (hostel_id, code) DO UPDATE SET
                          name = EXCLUDED.name,
                          bed_count = EXCLUDED.bed_count,
                          room_kind = EXCLUDED.room_kind,
                          inactive = EXCLUDED.inactive
                        """,
                        [code, rname, beds, inactive, hostel_name],
                    )

                c.execute(
                    """
                    INSERT INTO room_cleaning (room_id, status, full_taken, full_taken_mode, photos_before, photos_after, updated_at)
                    SELECT r.id, 'dirty', FALSE, '', '[]', '[]', CURRENT_TIMESTAMP
                    FROM rooms r
                    WHERE NOT EXISTS (SELECT 1 FROM room_cleaning rc WHERE rc.room_id = r.id)
                    """
                )

        self.stdout.write(self.style.SUCCESS("seed_initial_db: hostels + rooms + room_cleaning tayyor."))
