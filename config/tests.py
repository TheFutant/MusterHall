"""Tests for the project-level PWA endpoints."""

from django.test import TestCase
from django.urls import reverse


class PWAEndpointTests(TestCase):
    def test_manifest_served_unauthenticated(self):
        resp = self.client.get(reverse("manifest"))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp["Content-Type"], "application/manifest+json")
        body = resp.content.decode()
        self.assertIn("MusterHall", body)
        self.assertIn("standalone", body)
        self.assertIn("maskable", body)

    def test_service_worker_served_at_root_with_js_type(self):
        resp = self.client.get(reverse("service_worker"))
        self.assertEqual(resp.status_code, 200)
        # Must be served from the site root for whole-site scope.
        self.assertEqual(resp.request["PATH_INFO"], "/sw.js")
        self.assertIn("javascript", resp["Content-Type"])
        body = resp.content.decode()
        self.assertIn("musterhall-", body)        # versioned cache name
        self.assertIn("/offline/", body)          # offline fallback wired in

    def test_service_worker_not_long_cached(self):
        resp = self.client.get(reverse("service_worker"))
        self.assertIn("no-cache", resp.get("Cache-Control", ""))

    def test_offline_page(self):
        resp = self.client.get(reverse("offline"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "offline")

    def test_endpoints_reject_post(self):
        for name in ("manifest", "service_worker", "offline"):
            resp = self.client.post(reverse(name))
            self.assertEqual(resp.status_code, 405, name)
