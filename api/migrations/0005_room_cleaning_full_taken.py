from django.db import connection, migrations

from api.guest_identity import _get_table_columns


def forwards(apps, schema_editor):
    with schema_editor.connection.cursor() as c:
        cols = _get_table_columns(c, "room_cleaning")
        if "full_taken" not in cols:
            if connection.vendor == "sqlite":
                c.execute(
                    "ALTER TABLE room_cleaning ADD COLUMN full_taken INTEGER NOT NULL DEFAULT 0"
                    " CHECK (full_taken IN (0, 1))"
                )
            else:
                c.execute(
                    "ALTER TABLE room_cleaning ADD COLUMN full_taken BOOLEAN NOT NULL DEFAULT FALSE"
                )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [("api", "0004_booking_cancel_reason_fields")]

    operations = [migrations.RunPython(forwards, noop)]
