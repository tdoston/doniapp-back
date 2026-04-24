from django.db import migrations

from api.guest_identity import _get_table_columns


def forwards(apps, schema_editor):
    with schema_editor.connection.cursor() as c:
        cols = _get_table_columns(c, "bed_bookings")
        if "cancel_reason_bron" not in cols:
            c.execute("ALTER TABLE bed_bookings ADD COLUMN cancel_reason_bron TEXT NOT NULL DEFAULT ''")
        if "cancel_reason_checkin" not in cols:
            c.execute("ALTER TABLE bed_bookings ADD COLUMN cancel_reason_checkin TEXT NOT NULL DEFAULT ''")


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [("api", "0003_booking_kind_expected_arrival")]

    operations = [migrations.RunPython(forwards, noop)]
