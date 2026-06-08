import csv

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.db.models import Count, Sum
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.views.generic import (
    CreateView,
    DeleteView,
    DetailView,
    ListView,
    TemplateView,
    UpdateView,
)

from reference.models import Faction, SubFaction

from .filters import active_filter_values, filtered_entries
from .forms import CollectionEntryForm
from .models import (
    AssemblyState,
    BUILT_THRESHOLD,
    CollectionEntry,
    PAINTED_THRESHOLD,
    PaintState,
    SourceProduct,
    Tag,
)
from .roster_import import FACTION_ALIASES, parse_roster, plan_import

MAX_ROSTER_CHARS = 100_000
MAX_ROSTER_UNITS = 300


def _form_suggestions(user):
    """Autocomplete value lists scoped to the user, for form datalists."""
    entries = CollectionEntry.objects.filter(owner=user)
    return {
        "storage_options": sorted(
            {s for s in entries.values_list("storage_location", flat=True) if s}
        ),
        "source_options": list(
            SourceProduct.objects.filter(owner=user).values_list("name", flat=True)
        ),
        "tag_options": list(Tag.objects.filter(owner=user).values_list("name", flat=True)),
    }


class OwnerEntryMixin(LoginRequiredMixin):
    """Restrict object access to entries the user is allowed to see."""

    model = CollectionEntry

    def get_queryset(self):
        return CollectionEntry.objects.visible_to(self.request.user).with_related()


class DashboardView(LoginRequiredMixin, TemplateView):
    template_name = "collection/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        qs = CollectionEntry.objects.visible_to(self.request.user)

        total_items = qs.count()
        total_models = qs.aggregate(n=Sum("quantity"))["n"] or 0
        built_models = qs.filter(assembly_state__gte=BUILT_THRESHOLD).aggregate(n=Sum("quantity"))["n"] or 0
        painted_models = qs.filter(paint_state__gte=PAINTED_THRESHOLD).aggregate(n=Sum("quantity"))["n"] or 0
        ready_items = qs.filter(ready_for_game=True).count()

        def pct(part, whole):
            return round(part / whole * 100) if whole else 0

        def breakdown(field):
            rows = (
                qs.values(field)
                .annotate(items=Count("id"), models=Sum("quantity"))
                .order_by("-models")
            )
            return [
                {"label": r[field] or "Unassigned", "items": r["items"], "models": r["models"] or 0}
                for r in rows
            ]

        ctx.update(
            total_items=total_items,
            total_models=total_models,
            built_models=built_models,
            unbuilt_models=total_models - built_models,
            built_pct=pct(built_models, total_models),
            painted_models=painted_models,
            unpainted_models=total_models - painted_models,
            painted_pct=pct(painted_models, total_models),
            ready_items=ready_items,
            by_faction=breakdown("faction__name"),
            by_subfaction=breakdown("subfaction__name"),
            by_source=breakdown("source_product__name"),
        )
        return ctx


class CollectionListView(OwnerEntryMixin, ListView):
    template_name = "collection/entry_list.html"
    context_object_name = "entries"
    paginate_by = 24

    def get_queryset(self):
        return filtered_entries(self.request.user, self.request.GET)

    def get_template_names(self):
        if getattr(self.request, "htmx", False):
            return ["collection/_entry_list.html"]
        return [self.template_name]

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["filters"] = active_filter_values(self.request.GET)
        ctx["total_count"] = self.get_queryset().count()
        ctx["factions"] = Faction.objects.all()
        ctx["subfactions"] = SubFaction.objects.select_related("faction")
        ctx["sources"] = SourceProduct.objects.filter(owner=self.request.user)
        ctx["tags"] = Tag.objects.filter(owner=self.request.user)
        ctx["assembly_choices"] = AssemblyState.choices
        ctx["paint_choices"] = PaintState.choices
        return ctx


class CollectionDetailView(OwnerEntryMixin, DetailView):
    template_name = "collection/entry_detail.html"
    context_object_name = "entry"


class _EntryFormMixin:
    form_class = CollectionEntryForm

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["owner"] = self.request.user
        return kwargs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(_form_suggestions(self.request.user))
        ctx["NEW_ON_SPRUE_VALUE"] = AssemblyState.NEW_ON_SPRUE.value
        return ctx


class CollectionCreateView(LoginRequiredMixin, _EntryFormMixin, CreateView):
    model = CollectionEntry
    template_name = "collection/entry_form.html"

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f"Added “{self.object.name}”.")
        return response


class CollectionUpdateView(OwnerEntryMixin, _EntryFormMixin, UpdateView):
    template_name = "collection/entry_form.html"

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f"Updated “{self.object.name}”.")
        return response


class CollectionDeleteView(OwnerEntryMixin, DeleteView):
    template_name = "collection/entry_confirm_delete.html"
    success_url = reverse_lazy("collection:list")

    def form_valid(self, form):
        name = self.get_object().name
        response = super().form_valid(form)
        messages.success(self.request, f"Deleted “{name}”.")
        return response


def export_csv(request):
    """Stream the user's collection (honouring active filters) as CSV."""
    if not request.user.is_authenticated:
        return HttpResponse(status=403)

    qs = filtered_entries(request.user, request.GET)
    stamp = timezone.now().strftime("%Y%m%d")
    response = HttpResponse(content_type="text/csv")
    response["Content-Disposition"] = f'attachment; filename="musterhall_collection_{stamp}.csv"'

    writer = csv.writer(response)
    writer.writerow(
        [
            "Name", "Faction", "Chapter/Subfaction", "Quantity",
            "Assembly state", "Paint state", "Paint scheme",
            "Source product", "Storage location", "Tags",
            "Ready for game", "Backlog priority", "Notes",
            "Created", "Updated",
        ]
    )
    for e in qs:
        writer.writerow(
            [
                e.name,
                e.faction.name if e.faction else "",
                e.subfaction.name if e.subfaction else "",
                e.quantity,
                e.get_assembly_state_display(),
                e.get_paint_state_display(),
                e.paint_scheme,
                e.source_product.name if e.source_product else "",
                e.storage_location,
                ", ".join(t.name for t in e.tags.all()),
                "Yes" if e.ready_for_game else "No",
                e.get_backlog_priority_display() or "",
                e.notes,
                e.created.isoformat(),
                e.updated.isoformat(),
            ]
        )
    return response


# ---------------------------------------------------------------------------
# Roster import (paste/upload -> preview -> confirm -> collection entries)
# ---------------------------------------------------------------------------
def _read_roster_input(request):
    """Roster text from the uploaded file (precedence) or the textarea."""
    upload = request.FILES.get("roster_file")
    if upload:
        raw = upload.read()
        for encoding in ("utf-8", "latin-1"):
            try:
                return raw.decode(encoding)
            except UnicodeDecodeError:
                continue
        return ""
    return request.POST.get("roster_text", "")


def _resolve_factions(roster):
    """Best-effort match of roster faction/subfaction to shared reference data.

    Never creates reference rows. Returns (faction, subfaction, matched, warnings).
    """
    faction = subfaction = None
    warnings = []
    ftext = (roster.faction_text or "").strip()
    stext = (roster.subfaction_text or "").strip()

    if ftext:
        faction = Faction.objects.filter(name__iexact=ftext).first()
        if not faction:
            alias = FACTION_ALIASES.get(ftext.casefold())
            if alias:
                faction = Faction.objects.filter(name__iexact=alias).first()
    if faction and stext:
        subfaction = SubFaction.objects.filter(faction=faction, name__iexact=stext).first()

    matched = True
    if ftext and not faction:
        matched = False
        warnings.append(f"Faction “{ftext}” isn’t in your reference data — left blank on every unit.")
    elif stext and faction and not subfaction:
        warnings.append(f"Chapter “{stext}” isn’t listed under {faction.name} — left blank.")

    return faction, subfaction, matched, warnings


def _build_plan(roster, user, merge, skip_existing):
    """Run the pure planner with DB-backed matching + owned-name set injected."""
    faction, subfaction, matched, fwarnings = _resolve_factions(roster)

    def match_fn(unit):
        return faction, subfaction, matched, []

    existing = CollectionEntry.objects.filter(owner=user).values_list("name", flat=True)
    rows = plan_import(
        roster, match_fn=match_fn, existing_names=existing, merge=merge, skip_existing=skip_existing
    )
    return rows, fwarnings


@login_required
def roster_import(request):
    """GET: the import form. POST: parse and render the editable preview."""
    if request.method != "POST":
        return render(request, "collection/roster_import.html", {})

    text = _read_roster_input(request)
    if not text.strip():
        messages.error(request, "Paste a roster or choose a .txt file to import.")
        return render(request, "collection/roster_import.html", {})
    if len(text) > MAX_ROSTER_CHARS:
        messages.error(request, "That roster is too large to import (over 100 KB).")
        return render(request, "collection/roster_import.html", {})

    merge = request.POST.get("merge", "merge") != "separate"
    skip_existing = request.POST.get("skip_existing") == "on"

    roster = parse_roster(text)
    if len(roster.units) > MAX_ROSTER_UNITS:
        messages.error(request, f"That roster has more than {MAX_ROSTER_UNITS} units — please split it.")
        return render(request, "collection/roster_import.html", {})

    rows, fwarnings = _build_plan(roster, request.user, merge, skip_existing)
    context = {
        "roster": roster,
        "rows": list(enumerate(rows)),
        "roster_warnings": list(roster.warnings) + fwarnings,
        "raw_text": text,
        "merge": merge,
        "skip_existing": skip_existing,
        "default_tag": roster.list_name or "",
        "include_count": sum(1 for r in rows if not r.skip),
    }
    return render(request, "collection/roster_import_preview.html", context)


@login_required
def roster_import_confirm(request):
    """POST only: re-parse the raw text (authoritative) and create the chosen rows."""
    if request.method != "POST":
        return redirect("collection:roster_import")

    text = request.POST.get("raw", "")
    merge = request.POST.get("merge") == "1"
    skip_existing = request.POST.get("skip_existing") == "1"
    roster = parse_roster(text)
    rows, _ = _build_plan(roster, request.user, merge, skip_existing)

    source_name = (request.POST.get("source_text") or "").strip()
    tag_name = (request.POST.get("tag_text") or "").strip()

    created = 0
    with transaction.atomic():
        source = SourceProduct.objects.get_or_create(owner=request.user, name=source_name)[0] if source_name else None
        tag = Tag.objects.get_or_create(owner=request.user, name=tag_name)[0] if tag_name else None

        for i, row in enumerate(rows):
            if request.POST.get(f"include_{i}") != "on":
                continue
            try:
                qty = max(1, int(request.POST.get(f"qty_{i}", row.quantity)))
            except (TypeError, ValueError):
                qty = row.quantity
            entry = CollectionEntry(
                owner=request.user,
                name=row.name,
                faction=row.faction,
                subfaction=row.subfaction,
                quantity=qty,
                source_product=source,
                notes=row.notes,
            )
            entry.save()
            if tag:
                entry.tags.add(tag)
            created += 1

    if created:
        messages.success(request, f"Imported {created} unit{'' if created == 1 else 's'} into your collection.")
    else:
        messages.info(request, "Nothing was imported — no rows were selected.")

    if created and tag:
        return redirect(f"{reverse('collection:list')}?tag={tag.pk}")
    return redirect("collection:list")
