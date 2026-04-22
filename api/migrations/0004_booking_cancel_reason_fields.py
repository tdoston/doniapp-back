from django.db import migrations


def forwards(apps, schema_editor):
    with schema_editor.connection.cursor() as c:
        c.execute("PRAGMA table_info(bed_bookings)")
        cols = {row[1] for row in c.fetchall()}
        if "cancel_reason_bron" not in cols:
            c.execute("ALTER TABLE bed_bookings ADD COLUMN cancel_reason_bron TEXT NOT NULL DEFAULT ''")
        if "cancel_reason_checkin" not in cols:
            c.execute("ALTER TABLE bed_bookings ADD COLUMN cancel_reason_checkin TEXT NOT NULL DEFAULT ''")


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [("api", "0003_booking_kind_expected_arrival")]

    operations = [migrations.RunPython(forwards, noop)]
