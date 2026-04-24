"""PostgreSQL: avvalo biznes DDL; keyin `guests` va `bed_bookings.guest_id` (idempotent)."""

from django.db import migrations


def forwards(apps, schema_editor):
    from api.guest_identity import ensure_guest_schema
    from api.pg_bootstrap import apply_postgres_bootstrap_sql

    conn = schema_editor.connection
    apply_postgres_bootstrap_sql(conn)
    with conn.cursor() as c:
        ensure_guest_schema(c)


class Migration(migrations.Migration):
    dependencies = [("api", "0001_initial")]

    operations = [migrations.RunPython(forwards, migrations.RunPython.noop)]
