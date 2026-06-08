from django.conf import settings


def site(request):
    """Expose a couple of harmless site-wide flags to every template."""
    return {
        "SITE_NAME": "MusterHall",
        "REGISTRATION_OPEN": settings.REGISTRATION_OPEN,
    }
