from __future__ import annotations

from rest_framework import serializers

from .models import CancelReasonOption, Hostel, Room


class HostelSerializer(serializers.ModelSerializer):
    class Meta:
        model = Hostel
        fields = ("id", "name")


class RoomCatalogSerializer(serializers.ModelSerializer):
    """Taxta: `code` frontend `RoomData.id` sifatida."""

    class Meta:
        model = Room
        fields = ("code", "name", "bed_count", "inactive", "room_kind")


class CancelReasonSerializer(serializers.ModelSerializer):
    value = serializers.CharField(read_only=True, source="code")

    class Meta:
        model = CancelReasonOption
        fields = ("value", "label", "sort_order")
