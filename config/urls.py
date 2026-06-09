"""Root URL configuration for MusterHall."""

from django.conf import settings
from django.contrib import admin
from django.urls import include, path
from django.views.static import serve as media_serve

from . import pwa_views

urlpatterns = [
    path("admin/", admin.site.urls),
    # PWA: served from root so the service worker controls the whole site.
    path("manifest.webmanifest", pwa_views.manifest, name="manifest"),
    path("sw.js", pwa_views.service_worker, name="service_worker"),
    path("offline/", pwa_views.offline, name="offline"),
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
