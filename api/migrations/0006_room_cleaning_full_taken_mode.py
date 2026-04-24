from django.db import migrations


def forwards(apps, schema_editor):
    with schema_editor.connection.cursor() as c:
        c.execute("PRAGMA table_info(room_cleaning)")
        cols = {row[1] for row in c.fetchall()}
        if "full_taken_mode" not in cols:
            c.execute(
                "ALTER TABLE room_cleaning ADD COLUMN full_taken_mode TEXT NOT NULL DEFAULT '' CHECK (full_taken_mode IN ('', 'check_in', 'bron'))"
            )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [("api", "0005_room_cleaning_full_taken")]

    operations = [migrations.RunPython(forwards, noop)]
