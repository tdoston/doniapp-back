from django.db import migrations


def forwards(apps, schema_editor):
    with schema_editor.connection.cursor() as c:
        c.execute("PRAGMA table_info(room_cleaning)")
        cols = {row[1] for row in c.fetchall()}
        if "full_taken" not in cols:
            c.execute(
                "ALTER TABLE room_cleaning ADD COLUMN full_taken INTEGER NOT NULL DEFAULT 0 CHECK (full_taken IN (0, 1))"
            )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [("api", "0004_booking_cancel_reason_fields")]

    operations = [migrations.RunPython(forwards, noop)]
