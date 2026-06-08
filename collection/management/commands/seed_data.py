"""Seed reference lookups and a demo collection for local/homelab testing.

Idempotent: safe to run repeatedly (everything uses get_or_create). Rules-light
by design — only a GameSystemVersion stub plus factions, chapters, source
products and the owner's example units are created. No points/detachment data.
"""

import os

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from collection.models import AssemblyState, CollectionEntry, PaintState, SourceProduct, Tag
from reference.models import Faction, GameSystemVersion, SubFaction

User = get_user_model()

# subfaction code, source, qty, assembly, paint, ready, note, tags
A, P = AssemblyState, PaintState
ENTRIES = [
    ("Ballistus Dreadnought", "IF", "Imperial Fists Battalion Box", 1, A.ASSEMBLED, P.IN_PROGRESS, False, "", []),
    ("Redemptor Dreadnought", "IF", "Imperial Fists Battalion Box", 1, A.ASSEMBLED, P.PRIMED, False, "", []),
    ("Repulsor Executioner", "IF", "Imperial Fists Battalion Box", 2, A.NEW_ON_SPRUE, P.UNPAINTED, False, "", []),
    ("Vanguard Veterans", "IF", "Existing Collection", 1, A.ASSEMBLED, P.BASED, True, "", []),
    ("Chaplain with Jump Pack", "IF", "Existing Collection", 1, A.ASSEMBLED, P.PAINTED, True, "", ["character"]),
    ("Land Speeder", "CF", "Armageddon Launch Box, Space Marine Side", 1, A.NEW_ON_SPRUE, P.UNPAINTED, False, "", []),
    ("Eradicator Squad with Heavy Bolters", "IF", "Armageddon Launch Box, Space Marine Side", 1, A.CLIPPED, P.UNPAINTED, False, "", []),
    ("Intercessor Squad", None, "Existing Collection", 1, A.ASSEMBLED, P.PAINTED, True,
     "Can run as Crimson Fists or Imperial Fists.", ["flexible"]),
    ("Scout Squad", "CF", "Existing Collection", 1, A.ASSEMBLED, P.UNPAINTED, False, "", []),
    ("Infiltrator Squad", "CF", "Existing Collection", 1, A.ASSEMBLED, P.PRIMED, False, "", []),
    ("Incursor Squad", "CF", "Existing Collection", 1, A.NEW_ON_SPRUE, P.UNPAINTED, False, "", []),
    ("Eliminator Squad", "CF", "Existing Collection", 1, A.ASSEMBLED, P.PAINTED, True, "", []),
]


class Command(BaseCommand):
    help = "Seed reference data and a demo collection (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument("--username", default=os.environ.get("SEED_USERNAME", "hobbyist"))
        parser.add_argument("--password", default=os.environ.get("SEED_PASSWORD", "changeme123"))
        parser.add_argument("--email", default=os.environ.get("SEED_EMAIL", "hobbyist@example.com"))

    @transaction.atomic
    def handle(self, *args, **opts):
        version, _ = GameSystemVersion.objects.get_or_create(
            code="new40k",
            defaults={"name": "Warhammer 40,000 (New Edition)", "is_active": True,
                      "notes": "Placeholder version. Points/detachment data to be added later."},
        )

        astartes, _ = Faction.objects.get_or_create(name="Adeptus Astartes")
        chapters = {
            "IF": SubFaction.objects.get_or_create(faction=astartes, name="Imperial Fists")[0],
            "CF": SubFaction.objects.get_or_create(faction=astartes, name="Crimson Fists")[0],
        }

        user, created = User.objects.get_or_create(
            username=opts["username"], defaults={"email": opts["email"]}
        )
        if created:
            user.set_password(opts["password"])
            user.save()
            self.stdout.write(self.style.SUCCESS(
                f"Created user '{user.username}' (password: {opts['password']})"))
        else:
            self.stdout.write(f"User '{user.username}' already exists; leaving password unchanged.")

        sources = {}
        for name in {e[2] for e in ENTRIES}:
            sources[name] = SourceProduct.objects.get_or_create(owner=user, name=name)[0]

        added = 0
        for name, code, source, qty, assembly, paint, ready, note, tags in ENTRIES:
            entry, was_created = CollectionEntry.objects.get_or_create(
                owner=user,
                name=name,
                defaults={
                    "faction": astartes,
                    "subfaction": chapters.get(code),
                    "source_product": sources[source],
                    "quantity": qty,
                    "assembly_state": assembly,
                    "paint_state": paint,
                    "ready_for_game": ready,
                    "notes": note,
                },
            )
            if was_created:
                added += 1
                if tags:
                    tag_objs = [Tag.objects.get_or_create(owner=user, name=t)[0] for t in tags]
                    entry.tags.set(tag_objs)

        self.stdout.write(self.style.SUCCESS(
            f"Seed complete: version '{version.code}', faction '{astartes.name}', "
            f"{len(chapters)} chapters, {len(sources)} sources, {added} new collection entries."))
