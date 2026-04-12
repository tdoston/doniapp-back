from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("api.urls")),
]

admin.site.site_header = "DoniHostel admin"
admin.site.site_title = "DoniHostel"
