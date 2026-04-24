from django.contrib import admin
from django.urls import include, path, re_path
from django.views.generic import TemplateView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("api.urls")),
    path("", TemplateView.as_view(template_name="index.html"), name="spa-root"),
    re_path(
        r"^(?!api/|admin/|assets/|manifest\.webmanifest$|sw\.js$|workbox-.*\.js$|favicon\.ico$|apple-touch-icon\.png$|pwa-192\.png$|pwa-512\.png$).*$",
        TemplateView.as_view(template_name="index.html"),
        name="spa-fallback",
    ),
]

admin.site.site_header = "DoniHostel admin"
admin.site.site_title = "DoniHostel"
