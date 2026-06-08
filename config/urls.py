"""Root URL configuration for MusterHall."""

from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from django.views.static import serve as media_serve

urlpatterns = [
    path("admin/", admin.site.urls),
    # Built-in login/logout/password views, plus our signup view.
    path("accounts/", include("accounts.urls")),
    path("accounts/", include("django.contrib.auth.urls")),
    # Collection app owns the site root (dashboard + collection CRUD).
    path("", include("collection.urls")),
]

# Serve user-uploaded media. In DEBUG this also covers static() helpers; for a
# homelab we additionally serve media outside DEBUG when SERVE_MEDIA is on.
if settings.DEBUG or settings.SERVE_MEDIA:
    urlpatterns += [
        path(
            "media/<path:path>",
            media_serve,
            {"document_root": settings.MEDIA_ROOT},
        ),
    ]
