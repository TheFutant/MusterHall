"""User-owned collection models.

These hold what a user physically owns and its hobby state. They are kept
strictly separate from the shared ``reference`` rules data. Per-user isolation
is centralised in ``CollectionEntryQuerySet.visible_to`` so views, CSV export
and the dashboard cannot drift apart.
"""

import uuid
from pathlib import Path

from django.conf import settings
from django.db import models
from django.urls import reverse
from django.utils.text import slugify

from reference.models import Faction, SubFaction, TimeStampedModel


class AssemblyState(models.IntegerChoices):
    """How far along the build is. Gapped integers leave room to insert states
    later without a data migration, and let 'built vs unbuilt' be a SQL filter."""

    NEW_ON_SPRUE = 0, "New on sprue"
    CLIPPED = 10, "Clipped"
    ASSEMBLED = 20, "Assembled"


class PaintState(models.IntegerChoices):
    """Paint progress, independent of assembly progress."""

    UNPAINTED = 0, "Unpainted"
    PRIMED = 10, "Primed"
    IN_PROGRESS = 20, "In progress"
    PAINTED = 30, "Painted"
    BASED = 40, "Based"


class BacklogPriority(models.IntegerChoices):
    LOW = 10, "Low"
    MEDIUM = 20, "Medium"
    HIGH = 30, "High"


#: Thresholds used for the dashboard cross-tabs and derived properties.
BUILT_THRESHOLD = AssemblyState.ASSEMBLED
PAINTED_THRESHOLD = PaintState.PAINTED


def next_state_value(current, choices_enum):
    """The next value in an ordered IntegerChoices, wrapping past the end.

    Powers the at-the-table quick-toggle: one tap bumps a unit one step along
    (and from the final state back to the first, so a mis-tap is recoverable by
    tapping through). An unrecognised value resets to the first state.
    """
    values = [choice.value for choice in choices_enum]
    try:
        index = values.index(current)
    except ValueError:
        index = -1
    return values[(index + 1) % len(values)]


def collection_photo_path(instance, filename):
    """Per-user, collision-proof upload path. Never trusts the client filename."""
    ext = Path(filename).suffix.lower()[:10]
    owner_id = getattr(instance, "owner_id", None) or "unknown"
    return f"collection/{owner_id}/{uuid.uuid4().hex}{ext}"


class SourceProduct(TimeStampedModel):
    """Where models came from — a box set or a personal bucket. Per-user."""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="source_products")
    name = models.CharField(max_length=160)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["owner", "name"], name="uniq_source_per_owner"),
        ]
        indexes = [models.Index(fields=["owner"])]

    def __str__(self):
        return self.name


class Tag(TimeStampedModel):
    """A free-form organising label. Per-user, so two users can both have 'WIP'."""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="tags")
    name = models.CharField(max_length=60)
    slug = models.SlugField(max_length=60, blank=True)

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(fields=["owner", "name"], name="uniq_tag_name_per_owner"),
            models.UniqueConstraint(fields=["owner", "slug"], name="uniq_tag_slug_per_owner"),
        ]
        indexes = [models.Index(fields=["owner"])]

    def save(self, *args, **kwargs):
        if not self.slug:
            base = slugify(self.name)[:50] or "tag"
            candidate, suffix = base, 2
            qs = Tag.objects.filter(owner=self.owner)
            if self.pk:
                qs = qs.exclude(pk=self.pk)
            while qs.filter(slug=candidate).exists():
                candidate = f"{base}-{suffix}"
                suffix += 1
            self.slug = candidate
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class CollectionEntryQuerySet(models.QuerySet):
    def visible_to(self, user):
        """The single source of truth for who can see which entries.

        Staff/admin see everything; everyone else sees only their own. Used by
        every view, the CSV export and the dashboard so they cannot diverge.
        """
        if not user or not user.is_authenticated:
            return self.none()
        if user.is_staff:
            return self
        return self.filter(owner=user)

    def with_related(self):
        return self.select_related("faction", "subfaction", "source_product").prefetch_related("tags")


class CollectionEntry(TimeStampedModel):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="collection_entries")

    name = models.CharField(max_length=200, help_text="Unit or model name, e.g. 'Ballistus Dreadnought'.")
    faction = models.ForeignKey(Faction, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    subfaction = models.ForeignKey(
        SubFaction, on_delete=models.SET_NULL, null=True, blank=True, related_name="+",
        verbose_name="chapter / subfaction",
    )
    quantity = models.PositiveSmallIntegerField(default=1)

    assembly_state = models.PositiveSmallIntegerField(
        choices=AssemblyState.choices, default=AssemblyState.NEW_ON_SPRUE
    )
    paint_state = models.PositiveSmallIntegerField(
        choices=PaintState.choices, default=PaintState.UNPAINTED
    )
    paint_scheme = models.CharField(max_length=160, blank=True)

    source_product = models.ForeignKey(
        SourceProduct, on_delete=models.SET_NULL, null=True, blank=True, related_name="entries"
    )
    storage_location = models.CharField(max_length=160, blank=True)
    notes = models.TextField(blank=True)
    tags = models.ManyToManyField(Tag, blank=True, related_name="entries")
    photo = models.ImageField(upload_to=collection_photo_path, max_length=255, null=True, blank=True)

    ready_for_game = models.BooleanField(default=False)
    backlog_priority = models.PositiveSmallIntegerField(
        choices=BacklogPriority.choices, null=True, blank=True
    )

    objects = CollectionEntryQuerySet.as_manager()

    class Meta:
        ordering = ["-updated"]
        verbose_name_plural = "collection entries"
        indexes = [
            models.Index(fields=["owner", "faction"]),
            models.Index(fields=["owner", "subfaction"]),
            models.Index(fields=["owner", "assembly_state"]),
            models.Index(fields=["owner", "paint_state"]),
            models.Index(fields=["owner", "ready_for_game"]),
        ]
        constraints = [
            models.CheckConstraint(condition=models.Q(quantity__gte=1), name="entry_quantity_min_1"),
        ]

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse("collection:detail", args=[self.pk])

    # --- Derived hobby state (always filter/aggregate on the columns instead) --
    @property
    def is_built(self):
        return self.assembly_state >= BUILT_THRESHOLD

    @property
    def is_painted(self):
        return self.paint_state >= PAINTED_THRESHOLD

    @property
    def is_battle_ready(self):
        """Tabletop-ready in fact: fully assembled and at least painted."""
        return self.is_built and self.is_painted

    # --- One-tap state advance (the at-the-table quick-toggle) ----------------
    def advance_assembly(self):
        """Bump the build one step (wrapping). Caller saves."""
        self.assembly_state = next_state_value(self.assembly_state, AssemblyState)

    def advance_paint(self):
        """Bump the paint one step (wrapping). Caller saves."""
        self.paint_state = next_state_value(self.paint_state, PaintState)
