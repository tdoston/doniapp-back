# Boshlang'ich holat: managed=False — SQLite jadvallarini yaratmaydi.

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Hostel",
            fields=[
                ("id", models.AutoField(primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=200, unique=True)),
            ],
            options={
                "verbose_name": "Hostel",
                "verbose_name_plural": "Hostellar",
                "db_table": "hostels",
                "managed": False,
            },
        ),
        migrations.CreateModel(
            name="Room",
            fields=[
                ("id", models.AutoField(primary_key=True, serialize=False)),
                (
                    "hostel",
                    models.ForeignKey(
                        db_column="hostel_id",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="rooms",
                        to="api.hostel",
                    ),
                ),
                ("code", models.CharField(max_length=64)),
                ("name", models.CharField(max_length=255)),
                ("bed_count", models.PositiveSmallIntegerField()),
                ("room_kind", models.CharField(default="dorm", max_length=20)),
                ("photos", models.TextField(default="[]")),
            ],
            options={
                "verbose_name": "Xona",
                "verbose_name_plural": "Xonalar",
                "db_table": "rooms",
                "managed": False,
                "unique_together": {("hostel", "code")},
            },
        ),
        migrations.CreateModel(
            name="StaffUser",
            fields=[
                ("id", models.AutoField(primary_key=True, serialize=False)),
                ("login", models.CharField(max_length=64, unique=True)),
                ("display_name", models.CharField(max_length=200)),
                ("password_hash", models.CharField(max_length=255)),
                ("role", models.CharField(default="staff", max_length=20)),
                ("active", models.BooleanField(default=True)),
                ("created_at", models.TextField(blank=True, default="")),
            ],
            options={
                "verbose_name": "Jamoa a'zosi (API)",
                "verbose_name_plural": "Jamoa (API loginlari)",
                "db_table": "users",
                "managed": False,
            },
        ),
        migrations.CreateModel(
            name="BedBooking",
            fields=[
                ("id", models.CharField(max_length=36, primary_key=True, serialize=False)),
                (
                    "room",
                    models.ForeignKey(
                        db_column="room_id",
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="bed_bookings",
                        to="api.room",
                    ),
                ),
                ("bed_index", models.PositiveSmallIntegerField()),
                ("check_in_date", models.CharField(max_length=10)),
                ("nights", models.PositiveSmallIntegerField(default=1)),
                ("guest_name", models.CharField(blank=True, default="", max_length=200)),
                ("guest_phone", models.CharField(blank=True, default="", max_length=32)),
                ("price", models.FloatField(default=0)),
                ("paid", models.FloatField(default=0)),
                ("notes", models.TextField(blank=True, default="")),
                ("photos", models.TextField(default="[]")),
                ("checked_in_by", models.CharField(blank=True, default="", max_length=200)),
                ("status", models.CharField(default="active", max_length=20)),
                ("created_at", models.TextField(blank=True, default="")),
                ("updated_at", models.TextField(blank=True, default="")),
            ],
            options={
                "verbose_name": "Karavot broni",
                "verbose_name_plural": "Karavot bronlari",
                "db_table": "bed_bookings",
                "managed": False,
            },
        ),
        migrations.CreateModel(
            name="RoomCleaning",
            fields=[
                (
                    "room",
                    models.OneToOneField(
                        db_column="room_id",
                        on_delete=django.db.models.deletion.CASCADE,
                        primary_key=True,
                        related_name="cleaning",
                        serialize=False,
                        to="api.room",
                    ),
                ),
                ("status", models.CharField(default="dirty", max_length=20)),
                ("photos_before", models.TextField(default="[]")),
                ("photos_after", models.TextField(default="[]")),
                ("updated_at", models.TextField(blank=True, default="")),
            ],
            options={
                "verbose_name": "Xona tozaligi",
                "verbose_name_plural": "Xona tozaligi",
                "db_table": "room_cleaning",
                "managed": False,
            },
        ),
    ]
