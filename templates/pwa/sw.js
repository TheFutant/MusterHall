{% load static %}/* MusterHall service worker — rendered by Django so it always references the
 * current hashed static assets. Strategy, tuned for a multi-user app:
 *   - navigations: network-first, fall back to the offline page (never cache a
 *     user's private HTML — they always get fresh, correctly-authenticated pages)
 *   - hashed static assets: cache-first (immutable, content-addressed)
 *   - everything else (media, fragments, non-GET): straight to network
 */
const VERSION = "{{ cache_version }}";
const CACHE = "musterhall-" + VERSION;
const OFFLINE_URL = "{% url 'offline' %}";
const STATIC_PREFIX = "{{ static_prefix }}";

// Public, non-user-specific assets safe to precache.
const PRECACHE = [
  OFFLINE_URL,
  "{% static 'css/app.css' %}",
  "{% static 'js/htmx.min.js' %}",
  "{% static 'icons/icon-192.png' %}",
  "{% static 'icons/icon-512.png' %}",
  "{% static 'icons/apple-touch-icon.png' %}",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    (async () => {
      const cache = await caches.open(CACHE);
      // Tolerate a single bad entry instead of failing the whole install.
      await Promise.allSettled(PRECACHE.map((url) => cache.add(url)));
      self.skipWaiting();
    })()
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(
        keys.filter((k) => k.startsWith("musterhall-") && k !== CACHE).map((k) => caches.delete(k))
      );
      await self.clients.claim();
    })()
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);

  // Only handle our own GETs; let POSTs/HTMX writes and cross-origin pass through.
  if (req.method !== "GET" || url.origin !== self.location.origin) return;

  // Navigations: always try the network first so auth/data are never stale.
  if (req.mode === "navigate") {
    event.respondWith(
      (async () => {
        try {
          return await fetch(req);
        } catch (err) {
          const cache = await caches.open(CACHE);
          return (await cache.match(OFFLINE_URL)) || Response.error();
        }
      })()
    );
    return;
  }

  // Hashed static assets: cache-first, then populate the cache on miss.
  if (url.pathname.startsWith(STATIC_PREFIX)) {
    event.respondWith(
      (async () => {
        const cache = await caches.open(CACHE);
        const hit = await cache.match(req);
        if (hit) return hit;
        const res = await fetch(req);
        if (res && res.ok) cache.put(req, res.clone());
        return res;
      })()
    );
  }

  // Anything else (media photos, HTMX fragments): leave to the network.
});
