from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from reference.models import Faction, SubFaction

from .filters import filtered_entries
from .models import AssemblyState, CollectionEntry, PaintState, SourceProduct, Tag
from .roster_import import ParsedRoster, ParsedUnit, parse_roster, plan_import

User = get_user_model()


SAMPLE_ROSTER = """Darnath Force (1990 points)

Space Marines
Imperial Fists
Strike Force (2000 points)
Emperor's Shield


CHARACTERS

Ancient in Terminator Armour (95 points)
  • 1x Power fist
    1x Storm bolter
  • Enhancement: Malodraxian Standard

Darnath Lysander (100 points)
  • Warlord
  • 1x Fist of Dorn


BATTLELINE

Heavy Intercessor Squad (100 points)
  • 1x Heavy Intercessor Sergeant
    • 1x Bolt pistol
      1x Heavy bolt rifle
  • 4x Heavy Intercessor
    • 4x Bolt pistol
      4x Heavy bolt rifle


OTHER DATASHEETS

Ballistus Dreadnought (150 points)
  • 1x Armoured feet
    1x Ballistus lascannon

Ballistus Dreadnought (150 points)
  • 1x Armoured feet
    1x Ballistus lascannon

Terminator Assault Squad (360 points)
  • 1x Assault Terminator Sergeant
    • 1x Storm Shield
      1x Thunder hammer
  • 9x Assault Terminator
    • 9x Storm Shield
      9x Thunder hammer

Exported with App Version: v1.53.0 (119), Data Version: v780"""


def _null_match(unit):
    return None, None, True, []


def make_entry(owner, name="Test Unit", **kwargs):
    return CollectionEntry.objects.create(owner=owner, name=name, **kwargs)


class ModelTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("alice", password="pw12345!")

    def test_derived_state_properties(self):
        e = make_entry(self.user, assembly_state=AssemblyState.ASSEMBLED, paint_state=PaintState.PAINTED)
        self.assertTrue(e.is_built)
        self.assertTrue(e.is_painted)
        self.assertTrue(e.is_battle_ready)

        e2 = make_entry(self.user, name="WIP", assembly_state=AssemblyState.ASSEMBLED, paint_state=PaintState.PRIMED)
        self.assertTrue(e2.is_built)
        self.assertFalse(e2.is_painted)
        self.assertFalse(e2.is_battle_ready)

    def test_quantity_constraint(self):
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                make_entry(self.user, quantity=0)

    def test_tag_slug_is_per_owner(self):
        bob = User.objects.create_user("bob", password="pw12345!")
        t1 = Tag.objects.create(owner=self.user, name="Work In Progress")
        t2 = Tag.objects.create(owner=bob, name="Work In Progress")
        self.assertEqual(t1.slug, t2.slug)  # same slug allowed across owners

    def test_visible_to_isolation(self):
        bob = User.objects.create_user("bob", password="pw12345!")
        staff = User.objects.create_user("admin", password="pw12345!", is_staff=True)
        mine = make_entry(self.user, name="Mine")
        theirs = make_entry(bob, name="Theirs")

        self.assertEqual(set(CollectionEntry.objects.visible_to(self.user)), {mine})
        self.assertEqual(set(CollectionEntry.objects.visible_to(bob)), {theirs})
        self.assertEqual(set(CollectionEntry.objects.visible_to(staff)), {mine, theirs})


class FilterTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("alice", password="pw12345!")
        cls.astartes = Faction.objects.create(name="Adeptus Astartes")
        cls.orks = Faction.objects.create(name="Orks")
        cls.if_chapter = SubFaction.objects.create(faction=cls.astartes, name="Imperial Fists")
        make_entry(cls.user, name="Ballistus", faction=cls.astartes, subfaction=cls.if_chapter,
                   paint_state=PaintState.PAINTED)
        make_entry(cls.user, name="Boyz", faction=cls.orks, paint_state=PaintState.UNPAINTED)

    def test_filter_by_faction(self):
        qs = filtered_entries(self.user, {"faction": str(self.astartes.pk)})
        self.assertEqual([e.name for e in qs], ["Ballistus"])

    def test_filter_paint_bucket(self):
        self.assertEqual(filtered_entries(self.user, {"paint_state": "painted"}).count(), 1)
        self.assertEqual(filtered_entries(self.user, {"paint_state": "unpainted"}).count(), 1)

    def test_text_search(self):
        self.assertEqual([e.name for e in filtered_entries(self.user, {"q": "boy"})], ["Boyz"])

    def test_filter_no_chapter(self):
        # Boyz has a faction but no subfaction assigned.
        qs = filtered_entries(self.user, {"subfaction": "none"})
        self.assertEqual([e.name for e in qs], ["Boyz"])

    def test_filter_no_faction(self):
        make_entry(self.user, name="Unsorted Sprue")  # no faction at all
        qs = filtered_entries(self.user, {"faction": "none"})
        self.assertEqual([e.name for e in qs], ["Unsorted Sprue"])


class ViewCrudTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", password="pw12345!")
        cls.bob = User.objects.create_user("bob", password="pw12345!")

    def test_login_required(self):
        resp = self.client.get(reverse("collection:list"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/accounts/login/", resp["Location"])

    def test_create_sets_owner_and_resolves_source_and_tags(self):
        self.client.force_login(self.alice)
        resp = self.client.post(
            reverse("collection:create"),
            {
                "name": "Redemptor Dreadnought",
                "quantity": 1,
                "assembly_state": AssemblyState.ASSEMBLED,
                "paint_state": PaintState.PRIMED,
                "source_text": "Battalion Box",
                "tags_text": "WIP, magnetised",
            },
        )
        self.assertEqual(resp.status_code, 302)
        entry = CollectionEntry.objects.get(name="Redemptor Dreadnought")
        self.assertEqual(entry.owner, self.alice)
        self.assertEqual(entry.source_product.name, "Battalion Box")
        self.assertEqual(entry.source_product.owner, self.alice)
        self.assertEqual(set(entry.tags.values_list("name", flat=True)), {"WIP", "magnetised"})

    def test_cannot_view_or_edit_others_entry(self):
        bob_entry = make_entry(self.bob, name="Bob's Boyz")
        self.client.force_login(self.alice)
        self.assertEqual(self.client.get(reverse("collection:detail", args=[bob_entry.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("collection:update", args=[bob_entry.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("collection:delete", args=[bob_entry.pk])).status_code, 404)
        self.assertTrue(CollectionEntry.objects.filter(pk=bob_entry.pk).exists())

    def test_owner_can_delete(self):
        entry = make_entry(self.alice, name="Scrap")
        self.client.force_login(self.alice)
        resp = self.client.post(reverse("collection:delete", args=[entry.pk]))
        self.assertEqual(resp.status_code, 302)
        self.assertFalse(CollectionEntry.objects.filter(pk=entry.pk).exists())

    def test_list_htmx_returns_partial(self):
        make_entry(self.alice, name="Findable Unit")
        self.client.force_login(self.alice)
        resp = self.client.get(reverse("collection:list"), HTTP_HX_REQUEST="true")
        self.assertTemplateUsed(resp, "collection/_entry_list.html")
        self.assertTemplateNotUsed(resp, "collection/entry_list.html")
        self.assertContains(resp, "Findable Unit")


class QuickToggleTests(TestCase):
    """The at-the-table one-tap state advance (collection:quick_advance)."""

    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", password="pw12345!")
        cls.bob = User.objects.create_user("bob", password="pw12345!")

    def _url(self, entry, axis):
        return reverse("collection:quick_advance", args=[entry.pk, axis])

    def test_assembly_advances_and_wraps(self):
        entry = make_entry(self.alice, assembly_state=AssemblyState.NEW_ON_SPRUE)
        self.client.force_login(self.alice)
        sequence = [
            AssemblyState.CLIPPED,
            AssemblyState.ASSEMBLED,
            AssemblyState.NEW_ON_SPRUE,  # wraps back to the start
        ]
        for expected in sequence:
            resp = self.client.post(self._url(entry, "assembly"))
            self.assertEqual(resp.status_code, 200)
            entry.refresh_from_db()
            self.assertEqual(entry.assembly_state, expected)
            self.assertContains(resp, expected.label)

    def test_paint_advances_through_all_states_and_wraps(self):
        entry = make_entry(self.alice, paint_state=PaintState.UNPAINTED)
        self.client.force_login(self.alice)
        order = [
            PaintState.PRIMED,
            PaintState.IN_PROGRESS,
            PaintState.PAINTED,
            PaintState.BASED,
            PaintState.UNPAINTED,  # wraps
        ]
        for expected in order:
            self.client.post(self._url(entry, "paint"))
            entry.refresh_from_db()
            self.assertEqual(entry.paint_state, expected)

    def test_ready_toggles(self):
        entry = make_entry(self.alice, ready_for_game=False)
        self.client.force_login(self.alice)

        resp = self.client.post(self._url(entry, "ready"))
        entry.refresh_from_db()
        self.assertTrue(entry.ready_for_game)
        self.assertContains(resp, "Ready")

        self.client.post(self._url(entry, "ready"))
        entry.refresh_from_db()
        self.assertFalse(entry.ready_for_game)

    def test_returns_fragment_not_full_page(self):
        entry = make_entry(self.alice)
        self.client.force_login(self.alice)
        resp = self.client.post(self._url(entry, "assembly"))
        body = resp.content.decode()
        self.assertIn("state-controls", body)
        self.assertNotIn("<html", body)  # partial only, not the whole page

    def test_detail_request_emits_oob_resync(self):
        entry = make_entry(self.alice, assembly_state=AssemblyState.NEW_ON_SPRUE)
        self.client.force_login(self.alice)
        resp = self.client.post(self._url(entry, "assembly"), {"detail": "1"})
        body = resp.content.decode()
        # In-place controls plus out-of-band refreshes for the <dl> and badge.
        self.assertIn("state-controls", body)
        self.assertIn('hx-swap-oob="true"', body)
        self.assertIn('id="detail-assembly"', body)
        self.assertIn('id="detail-paint"', body)
        self.assertIn('id="detail-battle-ready"', body)
        self.assertIn(AssemblyState.CLIPPED.label, body)  # the new value

    def test_list_request_has_no_oob(self):
        entry = make_entry(self.alice)
        self.client.force_login(self.alice)
        resp = self.client.post(self._url(entry, "assembly"))  # no detail flag
        self.assertNotIn("hx-swap-oob", resp.content.decode())

    def test_detail_page_renders_interactive_controls(self):
        entry = make_entry(self.alice)
        self.client.force_login(self.alice)
        resp = self.client.get(reverse("collection:detail", args=[entry.pk]))
        self.assertContains(resp, 'class="state-controls"')
        self.assertContains(resp, 'id="detail-assembly"')   # OOB target present
        self.assertContains(resp, self._url(entry, "assembly"))
        self.assertContains(resp, 'hx-vals=')               # detail-context flag wired

    def test_unknown_axis_is_bad_request(self):
        entry = make_entry(self.alice)
        self.client.force_login(self.alice)
        resp = self.client.post(self._url(entry, "colour"))
        self.assertEqual(resp.status_code, 400)

    def test_get_not_allowed(self):
        entry = make_entry(self.alice)
        self.client.force_login(self.alice)
        resp = self.client.get(self._url(entry, "assembly"))
        self.assertEqual(resp.status_code, 405)

    def test_cannot_toggle_others_entry(self):
        bob_entry = make_entry(self.bob, assembly_state=AssemblyState.NEW_ON_SPRUE)
        self.client.force_login(self.alice)
        resp = self.client.post(self._url(bob_entry, "assembly"))
        self.assertEqual(resp.status_code, 404)
        bob_entry.refresh_from_db()
        self.assertEqual(bob_entry.assembly_state, AssemblyState.NEW_ON_SPRUE)

    def test_login_required(self):
        entry = make_entry(self.alice)
        resp = self.client.post(self._url(entry, "assembly"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/accounts/login/", resp["Location"])


class BulkEditTests(TestCase):
    """Bulk multi-select edit (collection:bulk_edit)."""

    url = reverse("collection:bulk_edit")

    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", password="pw12345!")
        cls.bob = User.objects.create_user("bob", password="pw12345!")

    def setUp(self):
        self.client.force_login(self.alice)
        self.e1 = make_entry(self.alice, name="Intercessors", paint_state=PaintState.UNPAINTED)
        self.e2 = make_entry(self.alice, name="Hellblasters", paint_state=PaintState.UNPAINTED)
        self.e3 = make_entry(self.alice, name="Redemptor", paint_state=PaintState.UNPAINTED)

    def _post(self, **data):
        return self.client.post(self.url, data)

    def test_set_paint_state_on_selected_only(self):
        resp = self._post(action="paint_state", value=PaintState.PAINTED,
                          ids=[self.e1.pk, self.e2.pk])
        self.assertEqual(resp.status_code, 200)
        self.e1.refresh_from_db(); self.e2.refresh_from_db(); self.e3.refresh_from_db()
        self.assertEqual(self.e1.paint_state, PaintState.PAINTED)
        self.assertEqual(self.e2.paint_state, PaintState.PAINTED)
        self.assertEqual(self.e3.paint_state, PaintState.UNPAINTED)  # not selected
        self.assertContains(resp, "Set paint state on 2 entries.")

    def test_set_assembly_state(self):
        self._post(action="assembly_state", value=AssemblyState.ASSEMBLED, ids=[self.e1.pk])
        self.e1.refresh_from_db()
        self.assertEqual(self.e1.assembly_state, AssemblyState.ASSEMBLED)

    def test_set_ready(self):
        self._post(action="ready_for_game", value="1", ids=[self.e1.pk, self.e2.pk])
        self.e1.refresh_from_db(); self.e2.refresh_from_db()
        self.assertTrue(self.e1.ready_for_game)
        self.assertTrue(self.e2.ready_for_game)
        self._post(action="ready_for_game", value="0", ids=[self.e1.pk])
        self.e1.refresh_from_db()
        self.assertFalse(self.e1.ready_for_game)

    def test_set_storage_location_and_clear(self):
        self._post(action="storage_location", value="Shelf B", ids=[self.e1.pk])
        self.e1.refresh_from_db()
        self.assertEqual(self.e1.storage_location, "Shelf B")
        self._post(action="storage_location", value="", ids=[self.e1.pk])
        self.e1.refresh_from_db()
        self.assertEqual(self.e1.storage_location, "")

    def test_add_tag_creates_and_assigns_per_user(self):
        self._post(action="add_tag", value="WIP", ids=[self.e1.pk, self.e2.pk])
        tag = Tag.objects.get(owner=self.alice, name="WIP")
        self.assertEqual(set(tag.entries.values_list("pk", flat=True)), {self.e1.pk, self.e2.pk})

    def test_add_existing_tag_is_idempotent(self):
        self._post(action="add_tag", value="WIP", ids=[self.e1.pk])
        self._post(action="add_tag", value="WIP", ids=[self.e1.pk])
        self.assertEqual(Tag.objects.filter(owner=self.alice, name="WIP").count(), 1)
        self.assertEqual(self.e1.tags.count(), 1)

    def test_delete_selected(self):
        resp = self._post(action="delete", ids=[self.e1.pk, self.e2.pk])
        self.assertContains(resp, "Deleted 2 entries.")
        self.assertFalse(CollectionEntry.objects.filter(pk__in=[self.e1.pk, self.e2.pk]).exists())
        self.assertTrue(CollectionEntry.objects.filter(pk=self.e3.pk).exists())

    def test_cannot_touch_other_users_entries(self):
        bob_entry = make_entry(self.bob, name="Bob's Boyz", paint_state=PaintState.UNPAINTED)
        resp = self._post(action="paint_state", value=PaintState.PAINTED,
                          ids=[self.e1.pk, bob_entry.pk])
        bob_entry.refresh_from_db()
        self.assertEqual(bob_entry.paint_state, PaintState.UNPAINTED)  # foreign id dropped
        self.assertContains(resp, "Set paint state on 1 entry.")       # only the owned one

    def test_invalid_paint_value_is_ignored(self):
        resp = self._post(action="paint_state", value="999", ids=[self.e1.pk])
        self.e1.refresh_from_db()
        self.assertEqual(self.e1.paint_state, PaintState.UNPAINTED)
        self.assertContains(resp, "Pick a paint state.")

    def test_nothing_selected(self):
        resp = self._post(action="paint_state", value=PaintState.PAINTED, ids=[])
        self.assertContains(resp, "Nothing selected.")

    def test_unknown_action_is_bad_request(self):
        resp = self._post(action="explode", ids=[self.e1.pk])
        self.assertEqual(resp.status_code, 400)

    def test_updated_is_bumped(self):
        before = timezone.now()
        self._post(action="paint_state", value=PaintState.PAINTED, ids=[self.e1.pk])
        self.e1.refresh_from_db()
        self.assertGreaterEqual(self.e1.updated, before)

    def test_response_has_oob_count_and_feedback(self):
        resp = self._post(action="ready_for_game", value="1", ids=[self.e1.pk])
        body = resp.content.decode()
        self.assertIn('id="result-count"', body)
        self.assertIn('id="bulk-feedback"', body)
        self.assertIn('hx-swap-oob="true"', body)

    def test_rerender_respects_active_filters(self):
        # Tag e1 only, then bulk-edit while filtering to that tag: the re-rendered
        # list must show just the tagged entry, not the whole collection.
        self._post(action="add_tag", value="Squad", ids=[self.e1.pk])
        tag = Tag.objects.get(owner=self.alice, name="Squad")
        resp = self._post(action="ready_for_game", value="1", ids=[self.e1.pk], tag=tag.pk)
        self.assertContains(resp, "Intercessors")
        self.assertNotContains(resp, "Hellblasters")

    def test_get_not_allowed(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)

    def test_login_required(self):
        self.client.logout()
        resp = self._post(action="paint_state", value=PaintState.PAINTED, ids=[self.e1.pk])
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/accounts/login/", resp["Location"])

    def test_list_page_renders_bulk_ui(self):
        resp = self.client.get(reverse("collection:list"))
        self.assertContains(resp, 'id="bulk-bar"')
        self.assertContains(resp, 'name="ids"')
        self.assertContains(resp, "js/bulk.js")


class ExportAndDashboardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.alice = User.objects.create_user("alice", password="pw12345!")
        cls.bob = User.objects.create_user("bob", password="pw12345!")
        make_entry(cls.alice, name="Alice Unit", quantity=3,
                   assembly_state=AssemblyState.ASSEMBLED, paint_state=PaintState.PAINTED)
        make_entry(cls.bob, name="Bob Secret Unit")

    def test_csv_export_is_owner_scoped(self):
        self.client.force_login(self.alice)
        resp = self.client.get(reverse("collection:export"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "text/csv")
        body = resp.content.decode()
        self.assertIn("Alice Unit", body)
        self.assertNotIn("Bob Secret Unit", body)

    def test_dashboard_counts(self):
        self.client.force_login(self.alice)
        resp = self.client.get(reverse("collection:dashboard"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["total_items"], 1)
        self.assertEqual(resp.context["total_models"], 3)
        self.assertEqual(resp.context["built_models"], 3)
        self.assertEqual(resp.context["painted_models"], 3)
        self.assertEqual(resp.context["painted_pct"], 100)


class RosterParserTests(TestCase):
    def test_parses_metadata_and_units(self):
        r = parse_roster(SAMPLE_ROSTER)
        self.assertEqual(r.list_name, "Darnath Force")
        self.assertEqual(r.total_points, 1990)
        self.assertEqual(r.faction_text, "Space Marines")
        self.assertEqual(r.subfaction_text, "Imperial Fists")
        self.assertEqual((r.game_size, r.points_limit), ("Strike Force", 2000))
        self.assertEqual(r.detachment_text, "Emperor's Shield")
        self.assertEqual(r.data_version, "v780")
        self.assertEqual([u.name for u in r.units].count("Ballistus Dreadnought"), 2)
        self.assertEqual(len(r.units), 6)

    def test_model_counts_and_flags(self):
        units = {u.name: u for u in parse_roster(SAMPLE_ROSTER).units}
        self.assertEqual(units["Heavy Intercessor Squad"].models, 5)
        self.assertEqual(units["Terminator Assault Squad"].models, 10)
        self.assertEqual(units["Darnath Lysander"].models, 1)
        self.assertTrue(units["Darnath Lysander"].warlord)
        self.assertEqual(units["Ancient in Terminator Armour"].enhancement, "Malodraxian Standard")

    def test_normalization_and_tolerance(self):
        # CRLF, × glyph, NBSP, and a garbage line should not crash the parser.
        text = "My List (5 points)\r\n\r\nOrks\r\n\r\nOTHER DATASHEETS\r\n\r\nBoyz (5 points)\r\n  • 10× Ork Boy\r\n??? junk line\r\n"
        r = parse_roster(text)
        self.assertEqual(r.list_name, "My List")
        self.assertEqual(len(r.units), 1)
        self.assertEqual(r.units[0].models, 1)  # no nested wargear -> single-block

    def test_empty_input(self):
        r = parse_roster("")
        self.assertEqual(r.units, [])
        self.assertTrue(r.warnings)


class ImportPlanTests(TestCase):
    def test_merge_collapses_duplicates_into_quantity(self):
        roster = parse_roster(SAMPLE_ROSTER)
        rows = plan_import(roster, match_fn=_null_match, existing_names=[], merge=True)
        names = [r.name for r in rows]
        self.assertEqual(len(rows), 5)  # two Ballistus merged
        ballistus = next(r for r in rows if r.name == "Ballistus Dreadnought")
        self.assertEqual(ballistus.quantity, 2)
        self.assertEqual(names.count("Ballistus Dreadnought"), 1)

    def test_keep_separate(self):
        roster = parse_roster(SAMPLE_ROSTER)
        rows = plan_import(roster, match_fn=_null_match, existing_names=[], merge=False)
        self.assertEqual(len(rows), 6)
        self.assertEqual([r.name for r in rows].count("Ballistus Dreadnought"), 2)

    def test_skip_existing_is_name_scoped(self):
        roster = parse_roster(SAMPLE_ROSTER)
        rows = plan_import(
            roster, match_fn=_null_match, existing_names=["ballistus dreadnought"],
            merge=True, skip_existing=True,
        )
        skipped = [r for r in rows if r.skip]
        self.assertEqual([r.name for r in skipped], ["Ballistus Dreadnought"])

    def test_long_name_truncated(self):
        roster = ParsedRoster(list_name="X", units=[ParsedUnit(name="A" * 250, points=10, section="X", models=1)])
        rows = plan_import(roster, match_fn=_null_match, existing_names=[], merge=True)
        self.assertEqual(len(rows[0].name), 200)
        self.assertTrue(any("truncat" in w.lower() for w in rows[0].warnings))

    def test_notes_capture_list_data(self):
        roster = parse_roster(SAMPLE_ROSTER)
        rows = plan_import(roster, match_fn=_null_match, existing_names=[], merge=True)
        lysander = next(r for r in rows if r.name == "Darnath Lysander")
        self.assertIn("Imported from list", lysander.notes)
        self.assertIn("Warlord", lysander.notes)
        self.assertIn("Emperor's Shield", lysander.notes)


class RosterImportViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("alice", password="pw12345!")
        cls.astartes = Faction.objects.create(name="Adeptus Astartes")
        cls.imperial_fists = SubFaction.objects.create(faction=cls.astartes, name="Imperial Fists")
        # Pre-existing owned unit, to exercise dedup-vs-collection.
        CollectionEntry.objects.create(owner=cls.user, name="Ballistus Dreadnought")

    def test_import_requires_login(self):
        resp = self.client.get(reverse("collection:roster_import"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/accounts/login/", resp["Location"])

    def test_preview_does_not_create_entries(self):
        self.client.force_login(self.user)
        before = CollectionEntry.objects.count()
        resp = self.client.post(reverse("collection:roster_import"), {"roster_text": SAMPLE_ROSTER, "merge": "merge"})
        self.assertEqual(resp.status_code, 200)
        self.assertTemplateUsed(resp, "collection/roster_import_preview.html")
        self.assertContains(resp, "Ballistus Dreadnought")
        self.assertEqual(CollectionEntry.objects.count(), before)

    def test_file_upload_path(self):
        self.client.force_login(self.user)
        upload = SimpleUploadedFile("army.txt", SAMPLE_ROSTER.encode(), content_type="text/plain")
        resp = self.client.post(reverse("collection:roster_import"), {"roster_file": upload})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Darnath Force")

    def test_confirm_creates_merged_entries_with_faction_match(self):
        self.client.force_login(self.user)
        data = {"raw": SAMPLE_ROSTER, "merge": "1", "skip_existing": "0", "tag_text": "Darnath Force"}
        for i in range(10):
            data[f"include_{i}"] = "on"
        resp = self.client.post(reverse("collection:roster_import_confirm"), data)
        self.assertEqual(resp.status_code, 302)

        imported = CollectionEntry.objects.filter(owner=self.user, tags__name="Darnath Force")
        self.assertEqual(imported.count(), 5)  # 6 units, two Ballistus merged
        ballistus = imported.get(name="Ballistus Dreadnought")
        self.assertEqual(ballistus.quantity, 2)
        # "Space Marines" alias -> Adeptus Astartes; "Imperial Fists" subfaction matched.
        self.assertEqual(ballistus.faction, self.astartes)
        self.assertEqual(ballistus.subfaction, self.imperial_fists)
        lysander = imported.get(name="Darnath Lysander")
        self.assertIn("Warlord", lysander.notes)

    def test_confirm_honours_unchecked_rows_and_quantity(self):
        self.client.force_login(self.user)
        data = {"raw": SAMPLE_ROSTER, "merge": "1", "skip_existing": "0", "tag_text": "Pick",
                "include_0": "on", "qty_0": "7"}
        resp = self.client.post(reverse("collection:roster_import_confirm"), data)
        self.assertEqual(resp.status_code, 302)
        imported = CollectionEntry.objects.filter(owner=self.user, tags__name="Pick")
        self.assertEqual(imported.count(), 1)
        self.assertEqual(imported.first().quantity, 7)

    def test_confirm_is_owner_scoped(self):
        bob = User.objects.create_user("bob", password="pw12345!")
        self.client.force_login(bob)
        data = {"raw": SAMPLE_ROSTER, "merge": "1", "skip_existing": "0", "tag_text": "Bobs"}
        for i in range(10):
            data[f"include_{i}"] = "on"
        self.client.post(reverse("collection:roster_import_confirm"), data)
        self.assertTrue(CollectionEntry.objects.filter(owner=bob, tags__name="Bobs").exists())
        self.assertFalse(CollectionEntry.objects.filter(owner=self.user, tags__name="Bobs").exists())
