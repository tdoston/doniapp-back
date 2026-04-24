"""Hostellar va xonalar — frontend `staticRooms.ts` bilan mos (idempotent)."""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import connection, transaction

# (hostel_name, room_code, display_name, bed_count) — `src/data/staticRooms.ts`
ROOM_SEED: list[tuple[str, str, str, int]] = [
    ("Vodnik", "v1", "1-qavat Zal", 4),
    ("Vodnik", "v2", "1-qavat Lux", 2),
    ("Vodnik", "v3", "1-qavat Koridor", 2),
    ("Vodnik", "v4", "2-qavat Zal", 4),
    ("Vodnik", "v5", "2-qavat Dvuxspalniy", 2),
    ("Vodnik", "v6", "2-qavat 2 Kishilik", 2),
    ("Vodnik", "v7", "2-qavat Koridor", 1),
    ("Zargarlik", "z1", "1-xona 7 ta krovat", 7),
    ("Zargarlik", "z2", "2-xona 3 ta krovat", 3),
    ("Zargarlik", "z3", "3-xona 1 ta krovat", 1),
    ("Zargarlik", "z4", "4-xona 3 ta krovat", 3),
    ("Tabarruk", "t1", "1-xona Dushli", 2),
    ("Tabarruk", "t2", "2-xona Dushli", 2),
    ("Tabarruk", "t3", "3-xona", 2),
    ("Tabarruk", "t4", "4-xona", 2),
    ("Tabarruk", "t5", "5-xona", 2),
    ("Tabarruk", "t6", "6-xona", 2),
    ("Tabarruk", "t7", "7-xona", 2),
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

                for hostel_name, code, rname, beds in ROOM_SEED:
                    c.execute(
                        """
                        INSERT INTO rooms (hostel_id, code, name, bed_count, room_kind, photos)
                        SELECT h.id, %s, %s, %s, 'dorm', '[]'
                        FROM hostels h
                        WHERE h.name = %s
                        ON CONFLICT (hostel_id, code) DO UPDATE SET
                          name = EXCLUDED.name,
                          bed_count = EXCLUDED.bed_count,
                          room_kind = EXCLUDED.room_kind
                        """,
                        [code, rname, beds, hostel_name],
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
