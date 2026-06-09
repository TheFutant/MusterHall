"""Render MusterHall's PWA / home-screen icons.

The icons are a flat deep-orange tile (matching the app accent) with three white
muster chevrons — military rank insignia, on-theme for a "muster hall" and
font-free so the result is deterministic and dependency-light.

Run once (and again whenever the look changes); the PNGs are committed under
``static/icons/`` and picked up by ``collectstatic``::

    python manage.py gen_pwa_icons
"""

from __future__ import annotations

from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

try:
    from PIL import Image, ImageDraw
except ImportError as exc:  # pragma: no cover - Pillow is a hard dependency
    raise SystemExit("Pillow is required: pip install Pillow") from exc

# Brand colours (kept in sync with --accent in static/css/app.css).
ORANGE = (194, 65, 12, 255)   # #c2410c
ORANGE_DARK = (154, 52, 10, 255)
WHITE = (255, 255, 255, 255)


def _rounded_tile(size: int, radius_ratio: float) -> Image.Image:
    """A flat orange rounded-square tile with a subtle vertical shade."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    radius = int(size * radius_ratio)
    draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=ORANGE)
    # Faint darker band along the bottom for a touch of depth.
    shade = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    sdraw = ImageDraw.Draw(shade)
    sdraw.rounded_rectangle(
        [0, int(size * 0.62), size - 1, size - 1], radius=radius, fill=ORANGE_DARK
    )
    return Image.alpha_composite(img, _soft(shade, size))


def _soft(layer: Image.Image, size: int) -> Image.Image:
    """Lower a layer's opacity so the shade reads as subtle, not a hard edge."""
    alpha = layer.getchannel("A").point(lambda a: int(a * 0.35))
    layer.putalpha(alpha)
    return layer


def _chevrons(img: Image.Image, content: float) -> None:
    """Draw three stacked downward chevrons centred in the tile.

    ``content`` is the fraction of the tile width the insignia spans, so callers
    can shrink it into a maskable safe-zone.
    """
    size = img.width
    draw = ImageDraw.Draw(img)
    cx = size / 2
    cy = size / 2

    span = size * content          # full width of a chevron
    thick = span * 0.20            # stroke thickness
    drop = span * 0.34             # how far the centre dips below the arms
    gap = thick * 1.65             # vertical spacing between chevrons
    half = span / 2

    # Stack three chevrons around the centre.
    for row in (-1, 0, 1):
        y_top = cy + row * gap - thick * 1.5
        x1, x2 = cx - half, cx + half
        points = [
            (x1, y_top),                       # left arm, top
            (cx, y_top + drop),                # centre, top (the V dip)
            (x2, y_top),                       # right arm, top
            (x2, y_top + thick),               # right arm, bottom
            (cx, y_top + drop + thick),        # centre, bottom (apex)
            (x1, y_top + thick),               # left arm, bottom
        ]
        draw.polygon(points, fill=WHITE)


class Command(BaseCommand):
    help = "Generate MusterHall PWA icons into static/icons/."

    def handle(self, *args, **options):
        out_dir = Path(settings.BASE_DIR) / "static" / "icons"
        out_dir.mkdir(parents=True, exist_ok=True)

        # (filename, size, corner-radius ratio, insignia span ratio)
        # Maskable / apple icons are near-full-bleed with the insignia pulled
        # into the safe zone so platform masks never clip it.
        specs = [
            ("icon-192.png", 192, 0.22, 0.62),
            ("icon-512.png", 512, 0.22, 0.62),
            ("icon-maskable-512.png", 512, 0.50, 0.46),
            ("apple-touch-icon.png", 180, 0.50, 0.56),
            ("favicon-32.png", 32, 0.22, 0.70),
        ]

        for name, size, radius_ratio, content in specs:
            tile = _rounded_tile(size, radius_ratio)
            _chevrons(tile, content)
            path = out_dir / name
            tile.save(path, "PNG")
            self.stdout.write(self.style.SUCCESS(f"  wrote {path.relative_to(settings.BASE_DIR)}"))

        self.stdout.write(self.style.SUCCESS(f"Done — {len(specs)} icons in {out_dir}"))
