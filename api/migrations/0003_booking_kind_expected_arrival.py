from django.db import migrations


def forwards(apps, schema_editor):
    with schema_editor.connection.cursor() as c:
        c.execute("PRAGMA table_info(bed_bookings)")
        cols = {row[1] for row in c.fetchall()}
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
