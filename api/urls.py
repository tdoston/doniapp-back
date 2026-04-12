from django.urls import path

from . import views

urlpatterns = [
    path("health", views.health),
    path("board", views.board),
    path("users", views.users),
    path("users/<int:user_id>", views.user_detail),
    path("guests/recent", views.guests_recent),
    path("guests/extract-name-from-id", views.guests_extract_id_name),
    path("cleaning", views.cleaning_list),
    path("cleaning/<str:room_code>", views.cleaning_patch),
    path("bookings", views.bookings_create),
    path("bookings/<uuid:booking_id>", views.booking_detail),
]
