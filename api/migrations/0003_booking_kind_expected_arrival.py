from django.db import migrations

from api.guest_identity import _get_table_columns


def forwards(apps, schema_editor):
    with schema_editor.connection.cursor() as c:
        cols = _get_table_columns(c, "bed_bookings")
        if "booking_kind" not in cols:
            c.execute(
                "ALTER TABLE bed_bookings ADD COLUMN booking_kind TEXT NOT NULL DEFAULT 'check_in'"
            )
        if "expected_arrival" not in cols:
            c.execute(
                "ALTER TABLE bed_bookings ADD COLUMN expected_arrival TEXT NOT NULL DEFAULT ''"
            )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [("api", "0002_guests_schema")]

    operations = [migrations.RunPython(forwards, noop)]
