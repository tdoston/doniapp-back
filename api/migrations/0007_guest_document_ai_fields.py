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
        cols = _column_names(c, "guests")
        if "doc_full_name" not in cols:
            c.execute("ALTER TABLE guests ADD COLUMN doc_full_name TEXT NOT NULL DEFAULT ''")
        if "doc_birth_date" not in cols:
            c.execute("ALTER TABLE guests ADD COLUMN doc_birth_date TEXT NOT NULL DEFAULT ''")
        if "doc_expiry_date" not in cols:
            c.execute("ALTER TABLE guests ADD COLUMN doc_expiry_date TEXT NOT NULL DEFAULT ''")
        if "doc_citizenship" not in cols:
            c.execute("ALTER TABLE guests ADD COLUMN doc_citizenship TEXT NOT NULL DEFAULT ''")
        if "doc_number" not in cols:
            c.execute("ALTER TABLE guests ADD COLUMN doc_number TEXT NOT NULL DEFAULT ''")
        if "doc_type" not in cols:
            c.execute("ALTER TABLE guests ADD COLUMN doc_type TEXT NOT NULL DEFAULT ''")
        if "doc_extracted_at" not in cols:
            c.execute("ALTER TABLE guests ADD COLUMN doc_extracted_at TEXT NOT NULL DEFAULT ''")


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [("api", "0006_room_cleaning_full_taken_mode")]

    operations = [migrations.RunPython(forwards, noop)]
