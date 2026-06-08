from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.test import TestCase
from django.urls import reverse

from reference.models import Faction, SubFaction

from .filters import filtered_entries
from .models import AssemblyState, CollectionEntry, PaintState, SourceProduct, Tag

User = get_user_model()


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
