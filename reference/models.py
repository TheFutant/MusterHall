"""Reference / rules-metadata models.

These are admin-curated and shared across all users. For the rules-light MVP
most tables stay empty: the *catalog* identity of a unit/detachment is stable,
while version-specific values (points, detachment costs) live in the ``*Profile``
tables keyed by GameSystemVersion so they can be added later without rewrites.
"""

from django.db import models
from django.utils.text import slugify


class TimeStampedModel(models.Model):
    """Abstract base that stamps creation/update times. Reused project-wide."""

    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


def unique_slug(instance, value, *, field="slug", queryset=None):
    """Return a slug for ``value`` unique within ``queryset`` (defaults to the
    model's table). Used by reference models that auto-fill blank slugs."""
    base = slugify(value)[:50] or "item"
    if queryset is None:
        queryset = type(instance)._default_manager.all()
    if instance.pk:
        queryset = queryset.exclude(pk=instance.pk)
    candidate = base
    suffix = 2
    while queryset.filter(**{field: candidate}).exists():
        candidate = f"{base}-{suffix}"
        suffix += 1
    return candidate


class GameSystemVersion(TimeStampedModel):
    """A versioned edition/ruleset snapshot, e.g. the new 40k launch dataset."""

    name = models.CharField(max_length=120)
    code = models.SlugField(max_length=40, unique=True, help_text="Short stable id, e.g. 'new40k'.")
    release_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-is_active", "name"]

    def __str__(self):
        return self.name


class Faction(TimeStampedModel):
    """Top-level faction, e.g. Adeptus Astartes. Shared reference data."""

    name = models.CharField(max_length=120, unique=True)
    slug = models.SlugField(max_length=60, unique=True, blank=True)

    class Meta:
        ordering = ["name"]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(self, self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class SubFaction(TimeStampedModel):
    """Chapter / subfaction within a Faction, e.g. Imperial Fists."""

    faction = models.ForeignKey(Faction, on_delete=models.CASCADE, related_name="subfactions")
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=60, blank=True)

    class Meta:
        ordering = ["faction__name", "name"]
        constraints = [
            models.UniqueConstraint(fields=["faction", "name"], name="uniq_subfaction_name_per_faction"),
            models.UniqueConstraint(fields=["faction", "slug"], name="uniq_subfaction_slug_per_faction"),
        ]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(self, self.name, queryset=SubFaction.objects.filter(faction=self.faction))
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} ({self.faction.name})"


class Keyword(TimeStampedModel):
    """Unit keyword / ability tag, e.g. INFANTRY, CHARACTER."""

    name = models.CharField(max_length=80, unique=True)
    slug = models.SlugField(max_length=80, unique=True, blank=True)

    class Meta:
        ordering = ["name"]

    def save(self, *args, **kwargs):
        if not self.slug:
            self.slug = unique_slug(self, self.name)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.name


class UnitCatalog(TimeStampedModel):
    """Stable catalog identity of a datasheet/unit. Version-agnostic."""

    game_system_version = models.ForeignKey(
        GameSystemVersion, on_delete=models.PROTECT, null=True, blank=True, related_name="units"
    )
    faction = models.ForeignKey(Faction, on_delete=models.CASCADE, related_name="units")
    name = models.CharField(max_length=160)
    unit_type = models.CharField(
        max_length=80, blank=True, help_text="Battlefield role / unit type, free text for now."
    )
    keywords = models.ManyToManyField(Keyword, blank=True, related_name="units")
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["faction__name", "name"]
        constraints = [
            models.UniqueConstraint(fields=["faction", "name"], name="uniq_unit_name_per_faction"),
        ]

    def __str__(self):
        return self.name


class Detachment(TimeStampedModel):
    """A detachment available to a faction. Version-agnostic identity."""

    faction = models.ForeignKey(Faction, on_delete=models.CASCADE, related_name="detachments")
    game_system_version = models.ForeignKey(
        GameSystemVersion, on_delete=models.PROTECT, null=True, blank=True, related_name="detachments"
    )
    name = models.CharField(max_length=160)
    description = models.TextField(blank=True)

    class Meta:
        ordering = ["faction__name", "name"]
        constraints = [
            models.UniqueConstraint(fields=["faction", "name"], name="uniq_detachment_name_per_faction"),
        ]

    def __str__(self):
        return self.name


class UnitPointProfile(TimeStampedModel):
    """Points for a unit at a given model count, for one game system version."""

    unit = models.ForeignKey(UnitCatalog, on_delete=models.CASCADE, related_name="point_profiles")
    game_system_version = models.ForeignKey(
        GameSystemVersion, on_delete=models.PROTECT, related_name="unit_point_profiles"
    )
    model_count = models.PositiveSmallIntegerField(default=1)
    points = models.PositiveIntegerField()
    faq_update_date = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["unit__name", "model_count"]
        constraints = [
            models.UniqueConstraint(
                fields=["unit", "game_system_version", "model_count"],
                name="uniq_unit_points_per_version_count",
            ),
        ]

    def __str__(self):
        return f"{self.unit.name} x{self.model_count}: {self.points} pts"


class DetachmentCostProfile(TimeStampedModel):
    """Versioned detachment point cost / allowance."""

    detachment = models.ForeignKey(Detachment, on_delete=models.CASCADE, related_name="cost_profiles")
    game_system_version = models.ForeignKey(
        GameSystemVersion, on_delete=models.PROTECT, related_name="detachment_cost_profiles"
    )
    points = models.PositiveIntegerField(default=0)
    faq_update_date = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["detachment__name"]
        constraints = [
            models.UniqueConstraint(
                fields=["detachment", "game_system_version"],
                name="uniq_detachment_cost_per_version",
            ),
        ]

    def __str__(self):
        return f"{self.detachment.name}: {self.points} pts"
