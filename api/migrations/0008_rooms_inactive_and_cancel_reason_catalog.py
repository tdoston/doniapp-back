"""rooms.inactive + cancel_reason_options + boshlang'ich sabablar."""

from __future__ import annotations

from django.db import connection, migrations, models


def seed_cancel_reasons(apps, schema_editor):
    CancelReasonOption = apps.get_model("api", "CancelReasonOption")
    booking = [
        ("no_show", "Mehmon kelmadi", 10),
        ("wrong_booking", "Bron xato / ma'lumot noto'g'ri", 20),
        ("early_leave", "Muddatidan oldin ketdi", 30),
        ("same_day_out", "O'sha kuni ketdi (check-out)", 40),
        ("other", "Boshqa sabab", 90),
    ]
    bron = [
        ("bron_wrong", "Bron xato / ma'lumot noto'g'ri", 10),
        ("bron_guest_cancelled", "Mehmon bronni bekor qildi", 20),
        ("bron_no_show", "Mehmon kelmadi yoki kelmaydi", 30),
        ("bron_plans_changed", "Reja o'zgardi (boshqa joy / muddat)", 40),
        ("other", "Boshqa sabab", 90),
    ]
    for code, label, order in booking:
        CancelReasonOption.objects.update_or_create(
            scope="booking_checkin",
            code=code,
            defaults={"label": label, "sort_order": order, "is_active": True},
        )
    for code, label, order in bron:
        CancelReasonOption.objects.update_or_create(
            scope="bron_board",
            code=code,
            defaults={"label": label, "sort_order": order, "is_active": True},
        )


def unseed_cancel_reasons(apps, schema_editor):
    CancelReasonOption = apps.get_model("api", "CancelReasonOption")
    CancelReasonOption.objects.filter(scope__in=("booking_checkin", "bron_board")).delete()


class Migration(migrations.Migration):
    dependencies = [("api", "0007_guest_document_ai_fields")]

    operations = [
        migrations.RunSQL(
            sql="ALTER TABLE rooms ADD COLUMN IF NOT EXISTS inactive BOOLEAN NOT NULL DEFAULT FALSE;",
            reverse_sql=migrations.RunSQL.noop,
        ),
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.AddField(
                    model_name="room",
                    name="inactive",
                    field=models.BooleanField(default=False),
                ),
            ],
        ),
        migrations.CreateModel(
            name="CancelReasonOption",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("scope", models.CharField(choices=[("booking_checkin", "Check-in bekor"), ("bron_board", "Taxta bron bekor")], db_index=True, max_length=32)),
                ("code", models.CharField(max_length=64)),
                ("label", models.CharField(max_length=255)),
                ("sort_order", models.PositiveSmallIntegerField(default=0)),
                ("is_active", models.BooleanField(default=True)),
            ],
            options={
                "db_table": "cancel_reason_options",
                "verbose_name": "Bekor sababi",
                "verbose_name_plural": "Bekor sabablari",
            },
        ),
        migrations.AddConstraint(
            model_name="cancelreasonoption",
            constraint=models.UniqueConstraint(fields=("scope", "code"), name="uniq_cancel_reason_scope_code"),
        ),
        migrations.RunPython(seed_cancel_reasons, unseed_cancel_reasons),
    ]
