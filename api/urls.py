from django.urls import path

from . import views
from .catalog_views import CancelReasonListView, HostelListView, RoomCatalogListView

urlpatterns = [
    path("catalog/hostels", HostelListView.as_view()),
    path("catalog/rooms", RoomCatalogListView.as_view()),
    path("catalog/cancel-reasons", CancelReasonListView.as_view()),
    path("health", views.health),
    path("doc-parse", views.doc_parse),
    path("board", views.board),
    path("users", views.users),
    path("users/<int:user_id>", views.user_detail),
    path("guests/recent", views.guests_recent),
    path("guests/history", views.guests_history),
    path("cleaning", views.cleaning_list),
    path("cleaning/<str:room_code>", views.cleaning_patch),
    path("bookings", views.bookings_create),
    path("bookings/<uuid:booking_id>", views.booking_detail),
]
