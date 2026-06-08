"""Shared filtering for the collection list, CSV export and counts.

Extracted into one place so the list view and the export can never disagree
about which rows match the active filters.
"""

from django.db.models import Q

from .models import (
    AssemblyState,
    CollectionEntry,
    PaintState,
    PAINTED_THRESHOLD,
)

# Special derived value for the "paint state" filter (painted vs unpainted),
# kept distinct from the exact PaintState choices.
PAINT_BUCKET_PAINTED = "painted"
PAINT_BUCKET_UNPAINTED = "unpainted"


def _as_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def filtered_entries(user, params):
    """Return the visible-to-user queryset narrowed by GET ``params``."""
    qs = CollectionEntry.objects.visible_to(user).with_related()

    faction = _as_int(params.get("faction"))
    if faction is not None:
        qs = qs.filter(faction_id=faction)

    subfaction = _as_int(params.get("subfaction"))
    if subfaction is not None:
        qs = qs.filter(subfaction_id=subfaction)

    assembly = _as_int(params.get("assembly_state"))
    if assembly is not None and assembly in AssemblyState.values:
        qs = qs.filter(assembly_state=assembly)

    paint = params.get("paint_state")
    if paint == PAINT_BUCKET_PAINTED:
        qs = qs.filter(paint_state__gte=PAINTED_THRESHOLD)
    elif paint == PAINT_BUCKET_UNPAINTED:
        qs = qs.filter(paint_state__lt=PAINTED_THRESHOLD)
    else:
        paint_exact = _as_int(paint)
        if paint_exact is not None and paint_exact in PaintState.values:
            qs = qs.filter(paint_state=paint_exact)

    source = _as_int(params.get("source_product"))
    if source is not None:
        qs = qs.filter(source_product_id=source)

    tag = _as_int(params.get("tag"))
    if tag is not None:
        qs = qs.filter(tags__id=tag)

    ready = params.get("ready_for_game")
    if ready in {"1", "true", "yes", "on"}:
        qs = qs.filter(ready_for_game=True)
    elif ready in {"0", "false", "no", "off"}:
        qs = qs.filter(ready_for_game=False)

    query = (params.get("q") or "").strip()
    if query:
        qs = qs.filter(
            Q(name__icontains=query)
            | Q(notes__icontains=query)
            | Q(paint_scheme__icontains=query)
            | Q(storage_location__icontains=query)
        )

    if tag is not None:
        qs = qs.distinct()  # tags join can duplicate rows
    return qs


def active_filter_values(params):
    """Echo the submitted filter values back for re-rendering the form."""
    return {
        "faction": params.get("faction", ""),
        "subfaction": params.get("subfaction", ""),
        "assembly_state": params.get("assembly_state", ""),
        "paint_state": params.get("paint_state", ""),
        "source_product": params.get("source_product", ""),
        "tag": params.get("tag", ""),
        "ready_for_game": params.get("ready_for_game", ""),
        "q": params.get("q", ""),
    }
