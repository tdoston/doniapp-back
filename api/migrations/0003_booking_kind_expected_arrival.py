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
        if "booking_kind" not in cols:
            c.execute(
                "ALTER TABLE bed_bookings ADD COLUMN booking_kind VARCHAR(16) NOT NULL DEFAULT 'check_in'"
            )
        if "expected_arrival" not in cols:
            c.execute(
                "ALTER TABLE bed_bookings ADD COLUMN expected_arrival VARCHAR(64) NOT NULL DEFAULT ''"
            )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [("api", "0002_guests_schema")]

    operations = [migrations.RunPython(forwards, noop)]
