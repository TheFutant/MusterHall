"""Progressive-web-app endpoints (manifest, service worker, offline shell).

These are served from the site root rather than ``/static/`` for two reasons:
the service worker needs root scope to control the whole app, and rendering them
as Django templates lets ``{% static %}`` resolve the hashed asset URLs that
WhiteNoise's manifest storage produces.
"""

from __future__ import annotations

import hashlib

from django.conf import settings
from django.shortcuts import render
from django.templatetags.static import static
from django.views.decorators.cache import cache_control
from django.views.decorators.http import require_GET

# Brand colours (kept in sync with --accent / dark --bg in static/css/app.css).
THEME_COLOR = "#c2410c"
BACKGROUND_COLOR = "#14171d"


def _base_ctx():
    return {
        "site_name": "MusterHall",
        "theme_color": THEME_COLOR,
        "background_color": BACKGROUND_COLOR,
    }


def _cache_version() -> str:
    """A token that changes whenever a precached asset's hashed name changes.

    Derived from the resolved (hashed) static URLs, so shipping new CSS/JS busts
    the service-worker cache automatically — no manual version bump needed.
    """
    try:
        assets = [static("css/app.css"), static("js/htmx.min.js")]
    except Exception:  # manifest not built yet (e.g. fresh dev checkout)
        assets = ["dev"]
    return hashlib.sha1("".join(assets).encode()).hexdigest()[:12]


@require_GET
def manifest(request):
    return render(
        request,
        "pwa/manifest.webmanifest",
        _base_ctx(),
        content_type="application/manifest+json",
    )


@require_GET
@cache_control(no_cache=True)
def service_worker(request):
    ctx = _base_ctx()
    ctx["static_prefix"] = settings.STATIC_URL
    ctx["cache_version"] = _cache_version()
    return render(request, "pwa/sw.js", ctx, content_type="text/javascript")


@require_GET
def offline(request):
    return render(request, "pwa/offline.html", _base_ctx())
