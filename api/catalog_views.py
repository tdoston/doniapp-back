from __future__ import annotations

from rest_framework import generics, status
from rest_framework.response import Response

from .models import CancelReasonOption, Hostel, Room
from .serializers import CancelReasonSerializer, HostelSerializer, RoomCatalogSerializer


class HostelListView(generics.ListAPIView):
    queryset = Hostel.objects.all().order_by("id")
    serializer_class = HostelSerializer
    pagination_class = None


class RoomCatalogListView(generics.ListAPIView):
    serializer_class = RoomCatalogSerializer
    pagination_class = None

    def get_queryset(self):
        hostel_name = (self.request.query_params.get("hostel") or "").strip()
        if not hostel_name:
            return Room.objects.none()
        return (
            Room.objects.filter(hostel__name=hostel_name, room_kind="dorm")
            .select_related("hostel")
            .order_by("id")
        )

    def list(self, request, *args, **kwargs):
        if not (request.query_params.get("hostel") or "").strip():
            return Response({"error": "hostel query param majburiy"}, status=status.HTTP_400_BAD_REQUEST)
        return super().list(request, *args, **kwargs)


class CancelReasonListView(generics.ListAPIView):
    serializer_class = CancelReasonSerializer
    pagination_class = None

    def get_queryset(self):
        raw = (self.request.query_params.get("scope") or CancelReasonOption.SCOPE_BOOKING_CHECKIN).strip()
        allowed = {CancelReasonOption.SCOPE_BOOKING_CHECKIN, CancelReasonOption.SCOPE_BRON_BOARD}
        scope = raw if raw in allowed else CancelReasonOption.SCOPE_BOOKING_CHECKIN
        return CancelReasonOption.objects.filter(is_active=True, scope=scope).order_by("sort_order", "code")
