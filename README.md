# MusterHall

A self-hosted, multi-user **Warhammer 40,000 collection manager** for the homelab.
The first release is **collection-first and rules-light**: it is the fastest way to
record what you own, what state it's in, how it's painted, where it's stored, and
what it belongs to — without pretending to be an official rules engine.

Built for the **new edition of Warhammer 40,000**. Official points, detachment
costs and unit data are added later, *by you*, through the admin — see
[Reference data & versioning](#reference-data--versioning).

> Not affiliated with or endorsed by Games Workshop. MusterHall stores your own
> collection data; it does not ship or replace official rules.

---

## Features (MVP)

- **Multi-user** with self-service signup (toggleable) and per-user data isolation.
  Each user only sees and edits their own collection; staff/admin see everything.
- **Collection entries** with: unit/model name, faction, chapter/subfaction,
  quantity, **build state** and **paint state** (tracked independently), paint
  scheme, source product/box, storage location, notes, tags, optional photo,
  a *ready-for-game* flag and a *backlog priority*.
- **One-tap state advance**: on the collection list **and each unit's detail
  page**, tap a unit's build, paint or ready badge to bump it one step —
  *clipped → assembled*, *in progress → painted → based*, or flip *ready for
  game* — without opening the edit form. Updates in place via HTMX (the detail
  page also out-of-band resyncs its summary fields), so it's ideal phone-in-hand
  at the painting table.
- **Filter & search**: faction, chapter/subfaction, build state, paint state,
  source product, tag, ready-for-game, and free text — live-updating via HTMX.
- **Dashboard**: total entries & models, built vs unbuilt, painted vs unpainted,
  ready-for-game count, and breakdowns by faction, subfaction and source product.
- **CSV export** of your collection (honouring the active filters).
- **Installable (PWA)**: add MusterHall to your phone's home screen and it
  launches fullscreen with its own icon — no app store, no separate mobile app.
  The UI is responsive and a friendly offline screen shows when your homelab is
  unreachable. (Service worker is network-first for pages, so your data is never
  cached stale or across users.)
- **Django admin** configured for every model.
- **Seed command** for instant demo data.
- **Foundations for the future** (army lists, points, detachments) modelled but
  hidden from the main UI.

## Stack

Django 5.2 (LTS) · PostgreSQL 16 · HTMX · PWA (installable + offline shell) ·
Docker Compose · WhiteNoise · Pillow.

---

## Quick start with Docker (recommended)

```bash
cp .env.example .env
# Edit .env: set DJANGO_SECRET_KEY and the POSTGRES_PASSWORD at minimum.

docker compose up --build -d
```

The web container waits for Postgres, runs migrations, and collects static files
on start. Then open <http://localhost:8000> (or your `WEB_PORT`).

**Create your admin account** (one-off):

```bash
docker compose exec web python manage.py createsuperuser
```

**Load the demo collection** (optional — factions, chapters, sources and the
example units):

```bash
docker compose exec web python manage.py seed_data
```

This creates a `hobbyist` user (default password `changeme123`, override with
`--password`). You can also auto-seed on first boot by setting `SEED_ON_START=true`
in `.env`.

To generate a secret key:

```bash
docker compose run --rm web python -c "from django.core.management.utils import get_random_secret_key as k; print(k())"
```

---

## Local development (no Docker)

A SQLite fallback kicks in automatically when no Postgres env vars are set, so you
can run everything locally with zero infrastructure:

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export DJANGO_DEBUG=True
python manage.py migrate
python manage.py seed_data        # optional demo data
python manage.py runserver
```

To develop against Postgres instead, set `POSTGRES_DB`, `POSTGRES_USER`,
`POSTGRES_PASSWORD`, `POSTGRES_HOST` (and optionally `DATABASE_URL`).

### Running tests

```bash
python manage.py test
```

Tests run on SQLite by default and cover the model state logic, per-user
isolation, the collection CRUD views, filtering, CSV export and signup.

---

## Configuration

All configuration is environment-driven (see `.env.example`). Highlights:

| Variable | Purpose | Default |
| --- | --- | --- |
| `DJANGO_SECRET_KEY` | **Required** outside DEBUG. | — |
| `DJANGO_DEBUG` | Developer mode. Keep `False` in production. | `False` |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated hosts. | `localhost,127.0.0.1` |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | Needed for https / custom origins. | — |
| `REGISTRATION_OPEN` | Allow self-service signup. | `True` |
| `SERVE_MEDIA` | Serve uploaded photos via Django. | `True` |
| `DJANGO_SECURE_SSL` | Enable HTTPS hardening (redirect + secure cookies). | `False` |
| `POSTGRES_DB` / `_USER` / `_PASSWORD` / `_HOST` / `_PORT` | Database. | — / sqlite fallback |
| `WEB_PORT` | Host port the app is published on. | `8000` |
| `SEED_ON_START` | Run `seed_data` on container start. | `false` |
| `DJANGO_SUPERUSER_*` | Auto-create a superuser on start. | — |

### Homelab notes

- For LAN-only use over plain HTTP the defaults are fine. Set
  `DJANGO_ALLOWED_HOSTS` to your host's name/IP and lock down `REGISTRATION_OPEN`
  once your players have registered.
- If you put it behind a reverse proxy with TLS, set `DJANGO_SECURE_SSL=True`,
  add your origin to `DJANGO_CSRF_TRUSTED_ORIGINS`, and let the proxy serve
  `/media/` and `/static/` for better performance (then set `SERVE_MEDIA=False`).
- **Photos** live in the `media` Docker volume and **Postgres** in `pgdata` —
  back these up. They persist across `docker compose up --build`.
- **Install on your phone**: open the site in your phone's browser and choose
  *Add to Home Screen* (Safari) or *Install app* (Chrome). The home-screen
  launch shows the app fullscreen with its own icon. Installability needs a
  secure context — `localhost` works for testing, but over the LAN browsers
  require HTTPS (see the reverse-proxy note above). The app icons are committed;
  regenerate them with `python manage.py gen_pwa_icons` if you re-theme.

---

## Data model

User-owned collection data is kept strictly separate from shared reference data.

**`collection`** (per-user, private)
- `CollectionEntry` — the core record. Build progress is two independent axes:
  `assembly_state` (*new on sprue → clipped → assembled*) and `paint_state`
  (*unpainted → primed → in progress → painted → based*). "Built", "painted" and
  "battle ready" are derived from these. Stored as gapped integers so new states
  can be inserted later without a data migration.
- `SourceProduct`, `Tag` — per-user lookups (your boxes, your labels).

**`reference`** (shared, admin-curated)
- `GameSystemVersion`, `Faction`, `SubFaction`, `Keyword`, `UnitCatalog`,
  `Detachment`, `UnitPointProfile`, `DetachmentCostProfile`.

**`armylist`** (experimental, admin-only for now)
- `ArmyList`, `ArmyListEntry` — the foundation for future list building. Links to
  collection/reference are nullable so they never block deletes in the core apps.

Per-user visibility lives in one place — `CollectionEntry.objects.visible_to(user)`
— reused by the list, dashboard and CSV export so they can never diverge.

### Reference data & versioning

Because new-edition data isn't fully published, the reference tables ship **empty**
(only a `GameSystemVersion` stub and the seeded factions/chapters). The design is
versioned so you can fill it in later without rework:

- A unit/detachment's **identity** (`UnitCatalog`, `Detachment`) is stable.
- Its **numbers** (points, detachment costs) live in `*Profile` tables keyed by
  `GameSystemVersion`, each with an optional FAQ/update date.

Add it all through the Django admin (`/admin/`) as official values land. MusterHall
prefers flexible storage and warnings over hard-coded, possibly-wrong rules.

---

## Project layout

```
config/         Django project (env-driven settings, URLs)
accounts/       Custom user model + signup
reference/      Shared, versioned rules/metadata (mostly to be filled later)
collection/     The MVP: models, filters, CRUD views, dashboard, CSV, seed_data
armylist/       Experimental list-building foundation (admin only)
config/pwa_views.py  Manifest, service worker and offline endpoints (root-scoped)
templates/      Base layout + auth templates (+ templates/pwa/ for the PWA)
static/         CSS + vendored HTMX + generated app icons (static/icons/)
Dockerfile, docker-compose.yml, entrypoint.sh, .env.example
```

## Roadmap

The data model is shaped toward, but the MVP deliberately does **not** implement:
list building (game size, points, detachments, enhancements, conflict warnings),
game logging, campaign management, and live game scoring.
