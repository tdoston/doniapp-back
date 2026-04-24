from django.db import migrations


def _column_names(c, table_name: str) -> set[str]:
    c.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = %s
        """,
        [table_name],
    )
    return {str(row[0]) for row in c.fetchall()}


def forwards(apps, schema_editor):
    with schema_editor.connection.cursor() as c:
        cols = _column_names(c, "bed_bookings")
        if "cancel_reason_bron" not in cols:
            c.execute("ALTER TABLE bed_bookings ADD COLUMN cancel_reason_bron TEXT NOT NULL DEFAULT ''")
        if "cancel_reason_checkin" not in cols:
            c.execute("ALTER TABLE bed_bookings ADD COLUMN cancel_reason_checkin TEXT NOT NULL DEFAULT ''")


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [("api", "0003_booking_kind_expected_arrival")]

    operations = [migrations.RunPython(forwards, noop)]
