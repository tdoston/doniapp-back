"""
PostgreSQL biznes jadvallari. ORM faqat admin / ko'rish uchun — `managed = False`.
"""

from __future__ import annotations

import uuid

from django.db import models


class Hostel(models.Model):
    id = models.AutoField(primary_key=True)
    name = models.CharField(max_length=200, unique=True)

    class Meta:
        managed = False
        db_table = "hostels"
        verbose_name = "Hostel"
        verbose_name_plural = "Hostellar"

    def __str__(self) -> str:
        return self.name


class Guest(models.Model):
    id = models.AutoField(primary_key=True)
    identity_key = models.CharField(max_length=96, unique=True)
    phone_normalized = models.CharField(max_length=32, blank=True, default="")
    passport_series = models.CharField(max_length=64, blank=True, default="")
    guest_name = models.CharField(max_length=200, blank=True, default="")
    doc_full_name = models.CharField(max_length=200, blank=True, default="")
    doc_birth_date = models.CharField(max_length=10, blank=True, default="")
    doc_expiry_date = models.CharField(max_length=10, blank=True, default="")
    doc_citizenship = models.CharField(max_length=64, blank=True, default="")
    doc_number = models.CharField(max_length=64, blank=True, default="")
    doc_type = models.CharField(max_length=40, blank=True, default="")
    doc_extracted_at = models.TextField(blank=True, default="")
    created_at = models.TextField(blank=True, default="")
    updated_at = models.TextField(blank=True, default="")

    class Meta:
        managed = False
        db_table = "guests"
        verbose_name = "Mehmon"
        verbose_name_plural = "Mehmonlar"

    def __str__(self) -> str:
        return f"{self.guest_name or '—'} · {self.identity_key}"


class Room(models.Model):
    id = models.AutoField(primary_key=True)
    hostel = models.ForeignKey(Hostel, models.CASCADE, db_column="hostel_id", related_name="rooms")
    code = models.CharField(max_length=64)
    name = models.CharField(max_length=255)
    bed_count = models.PositiveSmallIntegerField()
    room_kind = models.CharField(max_length=20, default="dorm")
    photos = models.TextField(default="[]")

    class Meta:
        managed = False
        db_table = "rooms"
        verbose_name = "Xona"
        verbose_name_plural = "Xonalar"
        unique_together = [("hostel", "code")]

    def __str__(self) -> str:
        return f"{self.hostel.name} · {self.code} ({self.name})"


class BedBooking(models.Model):
    id = models.CharField(primary_key=True, max_length=36, default=uuid.uuid4, editable=True)
    room = models.ForeignKey(Room, models.CASCADE, db_column="room_id", related_name="bed_bookings")
    bed_index = models.PositiveSmallIntegerField()
    check_in_date = models.CharField(max_length=10)
    nights = models.PositiveSmallIntegerField(default=1)
    guest_name = models.CharField(max_length=200, blank=True, default="")
    guest_phone = models.CharField(max_length=32, blank=True, default="")
    guest = models.ForeignKey(
        Guest,
        models.SET_NULL,
        db_column="guest_id",
        null=True,
        blank=True,
        related_name="bed_bookings",
    )
    price = models.FloatField(default=0)
    paid = models.FloatField(default=0)
    notes = models.TextField(blank=True, default="")
    photos = models.TextField(default="[]")
    checked_in_by = models.CharField(max_length=200, blank=True, default="")
    status = models.CharField(max_length=20, default="active")
    booking_kind = models.CharField(max_length=20, default="check_in")
    expected_arrival = models.CharField(max_length=120, blank=True, default="")
    cancel_reason_bron = models.TextField(blank=True, default="")
    cancel_reason_checkin = models.TextField(blank=True, default="")
    created_at = models.TextField(blank=True, default="")
    updated_at = models.TextField(blank=True, default="")

    class Meta:
        managed = False
        db_table = "bed_bookings"
        verbose_name = "Karavot broni"
        verbose_name_plural = "Karavot bronlari"

    def __str__(self) -> str:
        return f"{self.guest_name or '—'} · {self.room.code} #{self.bed_index} ({self.status})"


class RoomCleaning(models.Model):
    room = models.OneToOneField(Room, models.CASCADE, db_column="room_id", primary_key=True, related_name="cleaning")
    status = models.CharField(max_length=20, default="dirty")
    full_taken = models.BooleanField(default=False)
    full_taken_mode = models.CharField(max_length=20, default="")
    photos_before = models.TextField(default="[]")
    photos_after = models.TextField(default="[]")
    updated_at = models.TextField(blank=True, default="")

    class Meta:
        managed = False
        db_table = "room_cleaning"
        verbose_name = "Xona tozaligi"
        verbose_name_plural = "Xona tozaligi"


class StaffUser(models.Model):
    """Ilova `users` jadvali (Jamoa loginlari) — `auth.User` dan alohida."""

    id = models.AutoField(primary_key=True)
    login = models.CharField(max_length=64, unique=True)
    display_name = models.CharField(max_length=200)
    password_hash = models.CharField(max_length=255)
    role = models.CharField(max_length=20, default="staff")
    active = models.BooleanField(default=True)
    created_at = models.TextField(blank=True, default="")

    class Meta:
        managed = False
        db_table = "users"
        verbose_name = "Jamoa a'zosi (API)"
        verbose_name_plural = "Jamoa (API loginlari)"

    def __str__(self) -> str:
        return f"{self.login} ({self.display_name})"
