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
        cols = _column_names(c, "room_cleaning")
        if "full_taken_mode" not in cols:
            c.execute(
                "ALTER TABLE room_cleaning ADD COLUMN full_taken_mode VARCHAR(16) NOT NULL DEFAULT ''"
            )


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [("api", "0005_room_cleaning_full_taken")]

    operations = [migrations.RunPython(forwards, noop)]
