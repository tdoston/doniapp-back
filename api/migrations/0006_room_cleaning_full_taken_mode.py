from django.db import migrations

from api.guest_identity import _get_table_columns


def forwards(apps, schema_editor):
    with schema_editor.connection.cursor() as c:
        cols = _get_table_columns(c, "room_cleaning")
        if "full_taken_mode" not in cols:
            c.execute(
                "ALTER TABLE room_cleaning ADD COLUMN full_taken_mode TEXT NOT NULL DEFAULT ''"
                " CHECK (full_taken_mode IN ('', 'check_in', 'bron'))"
            )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [("api", "0005_room_cleaning_full_taken")]

    operations = [migrations.RunPython(forwards, noop)]
