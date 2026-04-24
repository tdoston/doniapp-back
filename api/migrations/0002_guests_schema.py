"""Idempotent: `guests` table and `bed_bookings.guest_id` column (SQLite + PostgreSQL)."""

from django.db import connection, migrations


def forwards(apps, schema_editor):
    from api.guest_identity import ensure_guest_schema

    with connection.cursor() as c:
        ensure_guest_schema(c)


class Migration(migrations.Migration):
    dependencies = [("api", "0001_initial")]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
