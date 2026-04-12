"""Biznes SQLite jadvallari admin panelda."""

from __future__ import annotations

import json
from datetime import date, timedelta

from django.contrib import admin
from django.db.models import IntegerField
from django.db.models.expressions import RawSQL
from django.utils import timezone
from django.utils.html import format_html
from django.utils.safestring import mark_safe

from .models import BedBooking, Guest, Hostel, Room, RoomCleaning, StaffUser

_MAX_INLINE_SRC = 2_500_000  # data URL xavfsizlik / brauzer


def _parse_photo_list(raw) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(x) for x in raw if isinstance(x, str) and x.strip()]
    s = (raw or "").strip()
    if not s:
        return []
    try:
        j = json.loads(s)
        if isinstance(j, list):
            return [str(x) for x in j if isinstance(x, str) and x.strip()]
    except json.JSONDecodeError:
        pass
    return []


def _photo_src_allowed(url: str) -> bool:
    u = url.strip()
    if not u or len(u) > _MAX_INLINE_SRC:
        return False
    if u.startswith(("https://", "http://")):
        return True
    if u.startswith("data:image/") and ";base64," in u:
        return True
    return False


class BookingWhenFilter(admin.SimpleListFilter):
    """Bugungi bronlarni tez topish (Asia/Tashkent)."""

    title = "Sana (tez)"
    parameter_name = "booking_when"

    def lookups(self, request, model_admin):
        return (
            ("checkin_today", "Bugun kirish (check-in)"),
            ("on_property_today", "Bugun joyda (stay, faqat active)"),
        )

    def queryset(self, request, queryset):
        today = timezone.localdate().isoformat()
        val = self.value()
        if val == "checkin_today":
            return queryset.filter(check_in_date=today)
        if val == "on_property_today":
            return (
                queryset.filter(status="active")
                .annotate(
                    _on_prop=RawSQL(
                        "(CASE WHEN bed_bookings.check_in_date <= %s AND %s < "
                        "date(bed_bookings.check_in_date, '+' || CAST(bed_bookings.nights AS TEXT) || ' days') "
                        "THEN 1 ELSE 0 END)",
                        [today, today],
                        output_field=IntegerField(),
                    )
                )
                .filter(_on_prop=1)
            )
        return queryset


class RoomInline(admin.TabularInline):
    model = Room
    extra = 0
    fields = ("code", "name", "bed_count", "room_kind")
    show_change_link = True


@admin.register(Hostel)
class HostelAdmin(admin.ModelAdmin):
    list_display = ("id", "name")
    search_fields = ("name",)
    inlines = [RoomInline]


@admin.register(Guest)
class GuestAdmin(admin.ModelAdmin):
    list_display = ("id", "identity_key", "guest_name", "phone_normalized", "passport_series", "updated_at")
    search_fields = ("identity_key", "guest_name", "phone_normalized", "passport_series")
    ordering = ("-updated_at",)


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ("id", "hostel", "code", "name", "bed_count", "room_kind")
    list_filter = ("hostel", "room_kind")
    search_fields = ("code", "name")
    raw_id_fields = ("hostel",)


@admin.register(BedBooking)
class BedBookingAdmin(admin.ModelAdmin):
    show_full_result_count = False
    ordering = ("-check_in_date", "-id")
    list_per_page = 30
    date_hierarchy = None

    class Media:
        css = {"all": ("admin/css/booking_admin.css",)}

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("room", "room__hostel")

    list_display = (
        "photos_thumb",
        "id_short",
        "room",
        "bed_index",
        "guest_name",
        "guest_phone",
        "check_in_date",
        "nights",
        "stay_until_display",
        "price",
        "paid",
        "balance_display",
        "status",
        "checked_in_by",
    )
    list_filter = (BookingWhenFilter, "status", "check_in_date")
    search_fields = ("guest_name", "guest_phone", "id", "notes")
    raw_id_fields = ("room",)
    readonly_fields = (
        "id",
        "summary_panel",
        "photos_gallery",
        "photos",
        "created_at",
        "updated_at",
    )
    fieldsets = (
        ("Ko‘rinish", {"fields": ("summary_panel", "photos_gallery")}),
        (
            "Mehmon",
            {
                "fields": (
                    "guest_name",
                    "guest_phone",
                    "notes",
                )
            },
        ),
        (
            "Xona va bron",
            {
                "fields": (
                    "room",
                    "bed_index",
                    "status",
                    "check_in_date",
                    "nights",
                )
            },
        ),
        (
            "To‘lov",
            {
                "fields": (
                    "price",
                    "paid",
                )
            },
        ),
        (
            "Texnik",
            {
                "fields": (
                    "id",
                    "checked_in_by",
                    "photos",
                    "created_at",
                    "updated_at",
                ),
                "classes": ("collapse",),
            },
        ),
    )

    @admin.display(description="Rasmlar")
    def photos_thumb(self, obj):
        urls = [u for u in _parse_photo_list(obj.photos) if _photo_src_allowed(u)][:3]
        if not urls:
            raw = _parse_photo_list(obj.photos)
            if raw:
                return format_html(
                    '<span class="booking-admin-badge" title="URL/data URL format ruxsat etilmagan">{} ta</span>',
                    len(raw),
                )
            return format_html('<span style="color:#94a3b8">—</span>')

        parts = []
        for u in urls:
            parts.append(
                format_html(
                    '<a href="{}" target="_blank" rel="noopener noreferrer">'
                    '<img src="{}" alt="" loading="lazy" /></a>',
                    u,
                    u,
                )
            )
        extra = len(_parse_photo_list(obj.photos)) - len(urls)
        tail = (
            format_html(' <span class="booking-admin-badge">+{}</span>', extra)
            if extra > 0
            else ""
        )
        return format_html(
            '<div class="booking-admin-thumbs">{}{}</div>',
            mark_safe("".join(str(p) for p in parts)),
            tail,
        )

    @admin.display(description="ID")
    def id_short(self, obj):
        s = str(obj.pk)
        if len(s) > 10:
            return format_html(
                '<code style="font-size:11px" title="{}">{}…</code>',
                s,
                s[:8],
            )
        return format_html("<code style='font-size:11px'>{}</code>", s)

    @admin.display(description="Chiqish")
    def stay_until_display(self, obj):
        """Oxirgi tun kuni (SQLite date() bilan bir xil mantiq)."""
        try:
            cin = obj.check_in_date
            if not cin or len(str(cin)) < 10:
                return "—"
            d0 = date.fromisoformat(str(cin)[:10])
            last = d0 + timedelta(days=max(0, int(obj.nights or 1) - 1))
            return last.isoformat()
        except (TypeError, ValueError):
            return "—"

    @admin.display(description="Qarz")
    def balance_display(self, obj):
        bal = float(obj.price or 0) - float(obj.paid or 0)
        if bal <= 0.009:
            return format_html('<span style="color:#15803d;font-weight:600">0</span>')
        return format_html('<span style="color:#b45309;font-weight:600">{:,.0f}</span>', bal)

    @admin.display(description="Batafsil")
    def summary_panel(self, obj):
        if not obj.pk:
            return format_html('<p style="color:#64748b">Saqlangandan keyin batafsil chiqadi.</p>')
        try:
            room = obj.room
            hostel = room.hostel.name
        except Exception:
            return format_html('<p style="color:#94a3b8">Xona yoki filial yuklanmadi.</p>')
        urls = [u for u in _parse_photo_list(obj.photos) if _photo_src_allowed(u)]
        return format_html(
            '<dl class="booking-admin-summary">'
            "<dt>Filial</dt><dd>{}</dd>"
            "<dt>Xona</dt><dd>{} · karavot #{}</dd>"
            "<dt>Mehmon</dt><dd>{} · {}</dd>"
            "<dt>Kirish → tunlar</dt><dd>{} → {} tun</dd>"
            "<dt>Rasmlar</dt><dd>{} ta (ko‘rinish: {})</dd>"
            "</dl>",
            hostel,
            room.code,
            obj.bed_index,
            obj.guest_name or "—",
            obj.guest_phone or "—",
            obj.check_in_date,
            obj.nights,
            len(_parse_photo_list(obj.photos)),
            len(urls),
        )

    @admin.display(description="Rasmlar (to‘liq)")
    def photos_gallery(self, obj):
        urls = [u for u in _parse_photo_list(obj.photos) if _photo_src_allowed(u)]
        if not urls:
            raw = _parse_photo_list(obj.photos)
            if not raw:
                return format_html('<p style="color:#94a3b8">Rasm yo‘q.</p>')
            return format_html(
                '<p style="color:#64748b">{} ta yozuv bor, lekin rasm URL/data URL sifatida '
                "ko‘rsatilmaydi (formatni tekshiring).</p>",
                len(raw),
            )
        blocks = []
        for i, u in enumerate(urls, start=1):
            blocks.append(
                format_html(
                    '<div class="booking-admin-gallery__item">'
                    '<a href="{}" target="_blank" rel="noopener noreferrer">'
                    '<img src="{}" alt="Rasm {}" loading="lazy" /></a>'
                    '<div class="booking-admin-gallery__cap">Rasm {} · yangi oynada ochish</div></div>',
                    u,
                    u,
                    i,
                    i,
                )
            )
        return format_html(
            '<div class="booking-admin-gallery">{}</div>',
            mark_safe("".join(str(b) for b in blocks)),
        )


@admin.register(RoomCleaning)
class RoomCleaningAdmin(admin.ModelAdmin):
    list_display = ("room", "cleaning_photos_thumb", "status", "updated_at")
    list_filter = ("status",)
    search_fields = ("room__code", "room__name")
    raw_id_fields = ("room",)
    readonly_fields = ("photos_gallery_before", "photos_gallery_after")

    class Media:
        css = {"all": ("admin/css/booking_admin.css",)}

    fieldsets = (
        (None, {"fields": ("room", "status", "updated_at")}),
        ("Rasmlar — oldin", {"fields": ("photos_gallery_before",)}),
        ("Rasmlar — keyin", {"fields": ("photos_gallery_after",)}),
        (
            "JSON (ilova)",
            {
                "fields": ("photos_before", "photos_after"),
                "classes": ("collapse",),
            },
        ),
    )

    @admin.display(description="Rasmlar")
    def cleaning_photos_thumb(self, obj):
        before = [u for u in _parse_photo_list(obj.photos_before) if _photo_src_allowed(u)][:1]
        after = [u for u in _parse_photo_list(obj.photos_after) if _photo_src_allowed(u)][:1]
        chunks = []
        if before:
            u = before[0]
            chunks.append(
                format_html(
                    '<div class="cleaning-admin-thumbs__group"><span>Oldin</span>'
                    '<a href="{}" target="_blank" rel="noopener"><img src="{}" alt="" /></a></div>',
                    u,
                    u,
                )
            )
        if after:
            u = after[0]
            chunks.append(
                format_html(
                    '<div class="cleaning-admin-thumbs__group"><span>Keyin</span>'
                    '<a href="{}" target="_blank" rel="noopener"><img src="{}" alt="" /></a></div>',
                    u,
                    u,
                )
            )
        if not chunks:
            nb = len(_parse_photo_list(obj.photos_before))
            na = len(_parse_photo_list(obj.photos_after))
            if nb or na:
                return format_html('<span class="booking-admin-badge">{}+{}</span>', nb, na)
            return format_html('<span style="color:#94a3b8">—</span>')
        return format_html(
            '<div class="cleaning-admin-thumbs">{}</div>',
            mark_safe("".join(str(c) for c in chunks)),
        )

    @staticmethod
    def _mini_gallery(label: str, raw: str):
        urls = [u for u in _parse_photo_list(raw) if _photo_src_allowed(u)]
        if not urls:
            return format_html("<p><strong>{}</strong>: —</p>", label)
        blocks = []
        for i, u in enumerate(urls, start=1):
            blocks.append(
                format_html(
                    '<div class="booking-admin-gallery__item">'
                    '<a href="{}" target="_blank" rel="noopener noreferrer">'
                    '<img src="{}" alt="" loading="lazy" /></a>'
                    '<div class="booking-admin-gallery__cap">{} · {}</div></div>',
                    u,
                    u,
                    label,
                    i,
                )
            )
        return format_html(
            '<div><p style="margin:0 0 8px;font-weight:600">{}</p><div class="booking-admin-gallery">{}</div></div>',
            label,
            mark_safe("".join(str(b) for b in blocks)),
        )

    @admin.display(description="Oldin rasmlar")
    def photos_gallery_before(self, obj):
        return self._mini_gallery("Oldin (do)", obj.photos_before)

    @admin.display(description="Keyin rasmlar")
    def photos_gallery_after(self, obj):
        return self._mini_gallery("Keyin (posle)", obj.photos_after)


@admin.register(StaffUser)
class StaffUserAdmin(admin.ModelAdmin):
    list_display = ("id", "login", "display_name", "role", "active", "created_at")
    list_filter = ("role", "active")
    search_fields = ("login", "display_name")
    readonly_fields = ("password_hash", "created_at")
