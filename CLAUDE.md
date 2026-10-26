# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

All development runs inside Docker.

```bash
# Start the full dev environment (web, DB, Redis, Memcached, Huey workers)
docker compose --profile web up

# Run the full test suite (4 xdist workers, each test class kept on one worker)
docker compose run --rm test pytest -n 4 --dist loadscope

# Run a specific test file or test (serial -- xdist worker startup costs ~7s)
docker compose run --rm test pytest camp/apps/monitors/tests.py -v
docker compose run --rm test pytest camp/apps/qaqc/tests.py::HealthCheckTests::test_grade_a_when_both_sensors_agree -v

# Run migrations / management commands
docker compose run --rm web python manage.py migrate
docker compose run --rm web python manage.py createsuperuser
```

Tests use `camp.settings.test` which runs Huey in immediate/synchronous mode and swaps in a local memory cache. Fixtures live in `/fixtures/*.yaml`.

Tests use `django.test.TestCase` with setup in the test methods or setUp and pytest-style assert statements (`assert x` instead of `self.isX()`).

## Pesticide Data Import

PUR data and chemical enrichment must be imported in order. Each step depends on the previous.

```bash
# 1. Import PUR use records (repeat for each year; imports reference tables on first run)
docker compose run --rm web python manage.py import_pur --year 2023
docker compose run --rm web python manage.py import_pur --year 2022 --skip-lookup

# 2. Enrich chemicals with CompTox (DTXSID, CAS numbers, IARC group)
#    Requires COMPTOX_API_KEY in .env
#    Phase 'search': batch name search + CAS lookup
#    Phase 'equals': slower individual search for high-volume unmatched chemicals (run after search)
#    Phase 'hazard': fetches IARC cancer classifications (requires DTXSIDs from search)
docker compose run --rm web python manage.py import_comptox --phase search
docker compose run --rm web python manage.py import_comptox --phase equals --limit 500 --workers 10
docker compose run --rm web python manage.py import_comptox --phase hazard

# 3. Apply Prop 65 carcinogen/reproductive/developmental toxin classifications
#    Download CSV manually from https://oehha.ca.gov/proposition-65/proposition-65-list
#    (site uses JS bot-protection that blocks server-side downloads)
docker compose run --rm web python manage.py import_prop65 --path /path/to/p65chemicalslist.csv

# 4. Apply CARB Toxic Air Contaminant classifications (17 CCR 93000/93001) from the
#    curated list in datafiles/toxic-air-contaminants.yaml; tags listed chemicals and
#    untags the rest. Not CARB's health-values table: most of its substances aren't TACs.
docker compose run --rm web python manage.py import_carbtac --dry-run
docker compose run --rm web python manage.py import_carbtac
```

Steps 2–4 are idempotent and safe to re-run. Re-running `import_pur` for a given year
deletes and reimports that year's records. Run `import_comptox --phase search` first whenever
new PUR years are added (new chemicals may appear); then re-run `equals` and `hazard`.

## SJVAPCD Forecast Setup

One-time setup, required per environment before the daily forecast task
(`fetch_forecasts`) will populate Kern, Tulare, and Sequoia forecasts. Must
run after county `Region`s are imported.

```bash
# 1. Import counties (if not already done)
docker compose run --rm web python manage.py import_counties

# 2. Derive and import the 3 SJVAPCD forecast zones that don't map 1:1 to a
#    county (Kern SJV Air Basin portion, Tulare valley portion, Sequoia
#    National Park and Forest), from the locally-saved forecast map SVG
#    (datafiles/sjvapcd-forecast-areas.svg)
docker compose run --rm web python manage.py import_forecast_zones
```

Idempotent and safe to re-run (updates the existing `Region`/`Boundary` records
rather than duplicating them). Until step 2 has run, the daily
`fetch_forecasts` task still ingests the other 6 zones that map directly to
a county — Kern, Tulare, and Sequoia rows are silently skipped (region not
found) rather than failing.

## Published Map Entry Types (DefaultCalibration fixture)

A `calibrations.DefaultCalibration` row for a (monitor type, entry type) pair is
what makes that pair appear on the map endpoints (`current/`, `at/`, `closest/`).
No row means the data is ingested and available via monitor detail / entries
endpoints, but not displayed. Only PM2.5 and O3 are meant to be on the map.
The rows live in `fixtures/default-calibrations.yaml` and are loaded manually,
not by migration. The fixture is pk-less (natural key on the pair), so loading
is idempotent and overwrites existing rows in place.

```bash
docker compose run --rm web python manage.py loaddata default-calibrations.yaml
```

Re-run whenever the fixture changes. To publish a new pair, add a row to the
fixture (blank `calibration` = default stage) and reload.

## VOZbox PM Cleanup

VOZbox carries a Plantower PMS and a Sensirion SEN5x, not a matched A/B pair,
so PM1/PM2.5/PM10 are stored RAW under sensors `plantower` / `sensirion` with
no processors or health checks. Environments that ingested VOZbox before that
change (any DB with VOZbox data from before PR #269) have rows named `a`/`b`
plus leftover CORRECTED/CLEANED/CALIBRATED PM2.5 entries, stale `LatestEntry`
rows, and `HealthCheck` rows. One command brings the data into the new shape:

```bash
# Count what would change; writes nothing
docker compose run --rm web python manage.py cleanup_vozbox_pm --dry-run

# Do it (batched, separately-committed, progress per batch)
docker compose run --rm web python manage.py cleanup_vozbox_pm

# Ease load / scope down if needed
docker compose run --rm web python manage.py cleanup_vozbox_pm --batch-size 2000 --sleep 0.5
docker compose run --rm web python manage.py cleanup_vozbox_pm --monitor-id e00fce6808784ceaf209f949
```

Idempotent and resumable; re-running reports `nothing to do`. It is deliberately
a command rather than a data migration -- the PM entry tables are large and
shared, and a one-shot UPDATE in the deploy path would hold locks against live
ingestion. Locally ~2.2M rows renamed in ~5 min and ~700k legacy rows removed in
~1.5 min while ingestion was running. On Heroku run it as a one-off dyno
(`heroku run -a <app> -- python manage.py cleanup_vozbox_pm`) after deploying and
loading the fixture above.

## BAM 1022 Mirror (staging / local dev only)

Production is the only environment where BAM 1022 devices push data. Staging and
local dev can mirror production's RAW BAM entries (and the monitors themselves,
with matching IDs) and run them through the normal processing pipeline. Enable
by setting `BAM_MIRROR_ENABLED=1` in the environment; leave it unset in production.
When enabled, an hourly task (`:20`) is registered that mirrors the last 3 hours.
The command alone defaults to the most recent hour. It reads production through
the official `sjvair` PyPI client (SJVAir/sjvair-python).

```bash
# Backfill a specific range (timestamps are UTC unless an offset is given)
docker compose run --rm web python manage.py mirror_bam_entries --start 2026-09-01T00:00 --end 2026-09-08T00:00

# Only one monitor
docker compose run --rm web python manage.py mirror_bam_entries --monitor-id GgeFGbo-Tjy3YYQqY0DLyA
```

Idempotent and safe to re-run.

## Region and Location Codes

Regions are referenced publicly by `(type, external_id)` and locations by
`(source, external_id)`. These codes are permanent and never reused, so imports
**retire** rows (`retired_at`, optionally `replaced_by`) instead of deleting them.

- The location import keeps child-care codes when the lowest license number closes.
- A CDP that incorporates is retired with `replaced_by` set to the new city.
- Staff can retire and un-retire regions and locations in the admin.
- Land use (`type=land_use`) is excluded from code lookup and the permanence promise:
  its codes come from OBJECTID and aren't stable.

Managers: `Region.all_objects` and `Location.all_objects` are unfiltered and are the
default and base managers; `objects` is current-only. Listings and searches use
`objects`. Anything that resolves a specific region or location from a request id or
code uses `all_objects`, so retired ones still answer. Resticus list endpoints default
to `_default_manager` (unfiltered), so pin listing querysets to `objects`.

After migrating on production, run `import_forecast_zones` (the 3 custom forecast
zones are missing there; see SJVAPCD Forecast Setup).

## Metadata Endpoints

- `GET /api/2.0/meta/datasets/` is the dataset catalog. Dataset and entry-type ids are
  permanent (a rename changes only the label). A pollutant's `available` flag comes
  from `DefaultCalibration`.
- `GET /api/2.0/meta/coverage/` returns first/last Pacific dates per dataset. It is
  computed on request, cached, and backed by the per-monitor unique index (no
  table-wide MIN/MAX on entry tables); there is no background task.

Timestamps: zone-less `timestamp__*` filter and `at/` values are read as Pacific,
explicitly, via `PacificDateTimeField`. `settings.TIME_ZONE` is UTC and
`TimezoneMiddleware` activates Pacific per request. Tests that use `RequestFactory`
bypass the middleware and `conftest.py` activates Pacific, so wrap Pacific-date
assertions in `timezone.override(None)`.

## Data Dashboard (`/workspace/`)

The data dashboard (SJVAir/data-dashboard) is built at deploy and embedded the way
monitor-map is: `invoke build` runs `scripts/import-data-dashboard.sh`, which clones
the dashboard's `main`, builds it (Node within its `engines`; npm refuses others), and
copies `dist/workspace/` into `dist/`, which `collectstatic` and the S3 sync pick up
unchanged. `camp/apps/workspace` serves `/workspace` and everything under it from a bare
template (no `base.html`: no GTM, Bulma, or site chrome), plus
`/workspace/manifest.webmanifest`. The repos' shared contract (file names, the
`sjvair-identity` block, the CSP list) is data-dashboard's spec 5a "Hosting contract";
change it there first.

```bash
# Build a dashboard branch or a local checkout (the checkout must be mounted)
docker compose run --rm -v ../data-dashboard:/data-dashboard:ro web \
  invoke import-data-dashboard --source /data-dashboard --ref foundations-5a-shipping

# A non-staff beta tester for the dashboard's embedding tests (DEBUG only; reads
# WORKSPACE_E2E_IDENTIFIER and WORKSPACE_E2E_PASSWORD)
docker compose run --rm web python manage.py seed_beta_tester
```

- **Beta gate:** `/workspace` is behind the `beta_tools` flag like `/tools/` (404 without
  it); "My Dashboard" is in the beta-only Data Tools menu. The manifest is exempt
  (browsers fetch it without cookies; it holds nothing private) and is sent `noindex`.
- **CSP:** built from `camp/apps/workspace/csp-hosts.json`, a byte-for-byte copy of
  data-dashboard's `csp-hosts.json`; update both together. `WORKSPACE_CSP_ENFORCE`
  (defaults to `DEBUG`: enforced locally, report-only in production until set to `1`
  before public go-live). `WORKSPACE_CSP_REPORT_URI` is the dashboard Sentry project's
  security endpoint; unset sends no reports.
- **Production config vars** (set by hand when shipping): `VITE_SENTRY_DSN`,
  `VITE_MAPTILER_KEY`, `VITE_NREL_KEY`, `WORKSPACE_CSP_REPORT_URI`, later
  `WORKSPACE_CSP_ENFORCE=1`. Never `VITE_PROD_URL` or `VITE_DEV_URL`. The Sentry ingest
  host must be in `csp-hosts.json` before the DSN is set.
- **Deferred with monitor-map's:** compression, cache headers, ordered uploads, and failing
  the release on an S3 upload error.
- **Load `app.js` by its exact static URL:** no `?v=` query string and no hashed or renamed
  copy (e.g. `ManifestStaticFilesStorage`). Hashed chunks import it back as `../app.js`, so
  a different URL loads it twice and the app boots twice. Don't cache-bust it to work around
  the missing `Cache-Control`.

## Architecture Overview

SJVAir is a Django/PostGIS air quality monitoring platform for the San Joaquin Valley. It ingests data from multiple sensor networks, processes it through a calibration pipeline, and exposes it via a versioned REST API.

### Core Data Model

**Monitors** (`camp/apps/monitors/`) are air quality devices. The base `Monitor` model has polymorphic subclasses via Django multi-table inheritance:
- `PurpleAir`, `AirGradient`, `AirNow`, `AQView`, `BAM`, `Methane`

Each monitor subclass defines an `ENTRY_CONFIG` dict that maps entry models to configuration (sensors, allowed stages, calibration processors). This config drives the entire data pipeline.

**Entries** (`camp/apps/entries/`) are time-series measurements. `BaseEntry` has subclasses per pollutant: `PM25`, `PM10`, `PM100`, `Particulates`, `Temperature`, `Humidity`, `Pressure`, `CO`, `CO2`, `NO2`, `O3`, `SO2`.

Entries move through stages: `RAW → CORRECTED → CLEANED → CALIBRATED`. Each stage is produced by a processor defined in `ENTRY_CONFIG`. `LatestEntry` tracks the most recent entry per monitor/type/processor combination.

**Health Checks** (`camp/apps/qaqc/`) run hourly per dual-channel monitor. `HealthCheckEvaluator` computes statistics (RPD, correlation, flatline ratio) for the two PM2.5 channels and assigns a score (0–3 / F–A). Results are stored in `HealthCheck` and linked back to the monitor via `monitor.health`.

**Calibrations** (`camp/apps/calibrations/`) hold trained regression models and processors. Processors are registered classes that transform one entry stage into the next. `DefaultCalibration` maps monitor type + entry type → which processor to use.

### API

Two versioned REST APIs at `/api/1.0/` and `/api/2.0/`, built on `django-resticus`. Key v2 endpoints:

- `GET /api/2.0/monitors/` — all monitors
- `GET /api/2.0/monitors/{type}/closest/` — nearest monitors by lat/lon
- `GET /api/2.0/monitors/{type}/current/` — monitors with recent healthy data
- `GET /api/2.0/monitors/{type}/at/` — monitors with data as of a historical timestamp (`?timestamp=`, `?region=`, `?bbox=`)
- `GET /api/2.0/monitors/{id}/entries/{type}/` — paginated entry list
- `GET /api/2.0/monitors/{id}/entries/{type}.csv` — CSV export

Serializers live next to their endpoints. Filters use `resticus.filters.FilterSet`. The `MonitorSerializer.fixup` pattern is used to add dynamic extra fields (health data, type-specific fields).

### Task Queue

Two Huey queues backed by Redis:
- **primary** — periodic tasks (cron) + sync work
- **secondary** — async one-off tasks

Task files: `camp/apps/*/tasks.py`. In tests, `MemoryHuey(immediate=True)` runs tasks inline.

### Settings

- `camp/settings/base.py` — main config
- `camp/settings/test.py` — overrides for tests (sync Huey, file email, local cache)
- `camp/settings/heroku.py` — production (S3, Memcached, SSL)

Key env vars: `DATABASE_URL`, `REDIS_URL`, `PURPLEAIR_READ_KEY`, `AIRNOW_API_KEY`, `CIMIS_API_KEY`, `TWILIO_*`, `AWS_*`.

### Data Science Utilities

`camp/datasci/` contains stats functions (`stats.py`), series comparison (`series.py`), and linear regression (`linear.py`). All stat functions return `Optional[float]` — they return `None` instead of `NaN` for edge cases (empty series, division by zero).

### Key Conventions

- **All new models use sqids** (`django_sqids`) for their external identifier — `sqid = SqidsField(alphabet=shuffle_alphabet('app.ModelName'))` alongside the default integer PK, following the pattern in `camp/apps/emissions/models/`. `SmallUUIDField` (`django-smalluuid`) only appears on legacy models predating this convention — do not use it for new models.
- Timezone is always `America/Los_Angeles`; `camp/utils/datetime.py` has helpers
- `Monitor.ENTRY_CONFIG` is the source of truth for what data a monitor produces and how it's processed
- `Monitor.supports_health_checks()` is an **instance method** — returns `True` only if this specific monitor instance supports dual-channel health checks (e.g., AirGradient requires `device == 'O-1PP'`)
- `Monitor.health_check_queryset_filter()` is a **classmethod** — returns a dict of queryset kwargs for filtering health-check-eligible monitors of that type in bulk
- All tests should inherit from Django's test case and use Django's fixtures system.
