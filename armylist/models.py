"""Experimental list-building foundation.

Not exposed in the main UI yet — these models exist so list building can be
layered on later once New40k points/detachment data is available. FKs into the
collection/reference apps are nullable + SET_NULL so this experimental app can
never block deletes in the core apps.
"""

from django.conf import settings
from django.db import models

from reference.models import Detachment, GameSystemVersion, TimeStampedModel, UnitCatalog


class ArmyList(TimeStampedModel):
    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="army_lists")
    name = models.CharField(max_length=160)
    game_system_version = models.ForeignKey(
        GameSystemVersion, on_delete=models.SET_NULL, null=True, blank=True, related_name="army_lists"
    )
    detachment = models.ForeignKey(
        Detachment, on_delete=models.SET_NULL, null=True, blank=True, related_name="army_lists"
    )
    points_limit = models.PositiveIntegerField(null=True, blank=True)
    notes = models.TextField(blank=True)
    is_experimental = models.BooleanField(default=True)

    class Meta:
        ordering = ["-updated"]

    def __str__(self):
        return self.name


class ArmyListEntry(TimeStampedModel):
    army_list = models.ForeignKey(ArmyList, on_delete=models.CASCADE, related_name="entries")
    # Optional links; the typed name survives if either reference is removed.
    collection_entry = models.ForeignKey(
        "collection.CollectionEntry", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    unit_catalog = models.ForeignKey(
        UnitCatalog, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    name = models.CharField(max_length=200)
    quantity = models.PositiveSmallIntegerField(default=1)
    points = models.PositiveIntegerField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "army list entries"

    def __str__(self):
        return self.name
