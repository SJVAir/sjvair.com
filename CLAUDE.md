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

## CIMIS Weather Summaries

CIMIS stations get monitor summaries (hour up to year) for 11 types: `temperature`,
`humidity`, `dewpoint`, `soiltemperature`, `windspeed`, `precipitation`, `solarradiation`,
`netradiation`, `vaporpressure`, `eto`, `etr`. `winddirection` stays raw. There are never region
rows for weather: region paths use the entry models' `summarize` flag only.

- **The switch** is per monitor type: `'summarize': True` on an entry type in `ENTRY_CONFIG`.
  `camp/apps/summaries/selection.py` is the one place that picks entry types (`is_summarized`,
  `monitor_summary_entry_models`, `region_summary_entry_models`, `switch_entry_types`,
  `switch_entry_models`, `monitor_types_summarizing`). Air quality is unchanged: the model flag
  still drives it, and the `:45` / `:50` hourly parents skip the switch types.
- **On arrival**: the CIMIS ingest calls `summarize_monitor_hours` for the hours it wrote
  (import and finalize both). `finalize_cimis_data` also re-summarizes all of yesterday
  (Pacific) for every station and re-rolls the finished periods, changed or not.
- **Settle margins**: switch types use `LATE_SETTLE_MARGIN` (`schedule.py`: hour 30h,
  day and longer 7h) because CIMIS data lands late; the summaries cache rule uses it for them.
- **Timestamps**: readings are stamped at the START of the hour the record covers, in fixed
  UTC-8 (`CIMIS_TZ`, `CIMIS.parse_timestamp`; hour 2400 is 23:00 of the record's date). Rows
  ingested before this were stamped the old way (`legacy_timestamp`: end of the hour, Pacific
  wall clock) and must be re-stamped.

Order for an environment: deploy, `restamp_cimis` per station, then rebuild per station.

```bash
# 1. Re-stamp (always from the station's first stored date through today, Pacific)
docker compose run --rm web python manage.py restamp_cimis --monitor <id> --dry-run
docker compose run --rm web python manage.py restamp_cimis --monitor <id> [--monitor <id> ...]

# 2. Build the summaries (per station, from the first CIMIS date)
docker compose run --rm web python manage.py rebuild_summaries <first CIMIS date> <today> \
  --monitor <id> --monitors-only
```

`restamp_cimis` (`camp/apps/monitors/cimis/restamp.py`) fetches every date first, skips and
counts malformed records, and aborts a station when a date with stored rows comes back empty.
One transaction per station; it rebuilds `LatestEntry`. A collision with live ingest aborts
that station, and a re-run is safe. Dry-run the largest station first. Run it away from
:40-:50 (the live import runs at :45); a collision may still log one `IntegrityError` in the
live import, which its next run self-heals. There is no `--end`: the delete window ends at 00:00
of the day after the last date, which in PST is that next day's new-style 0100 row, so a past
end would delete an hour it never re-fetches.

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
- **Scale shape** (`camp/utils/scales.py`): `{id, label, units, kind: range|category, source,
  levels[]}`; a level is `{key, label, color, tier, description, guidance, min, max, value,
  opacity}`. Scale ids are catalog entry-type ids and level `key`s are permanent. Ranges are
  half-open (`min <= value < max`) and the top level's `max` is `null`; categories use `value`.
  `tier` is 0-4 or `null` (no severity). `description` is the official wording (credited via
  `source`); `guidance` is SJVAir's own and is `""` for AQ Good and heat Low.
- **Domain meta endpoints** (each a catalog `meta_url`): `calheatscore/meta/`, `hms/meta/` and
  `forecasts/meta/` return scales keyed by catalog entry-type id (forecasts also lists the
  zones with their regions). `pesticides/meta/` lists `categories` (with `in_use`),
  `iarc_groups`, `methods` (the use records' G/A/F/O/none, not SprayDays' notice methods),
  `narrows` and `placeholder_chemicals`; it's both pesticide datasets' `meta_url`. The
  pesticide entity search (`pesticides/search/`) returns one page plus `more`, and a
  `placeholder` flag on chemical results. `monitors/meta/` adds a `scale` per entry type plus `stages` and
  `processors` labels. It no longer serves the legacy `levels` dict; `scale` is the only level
  format. Each entry type has `school_guidelines` (null except `pm25`), defined in
  `camp/apps/entries/guidelines.py`: activity keys are permanent, the text is verbatim from the
  old schools page, and the `/guidelines/` pages render from the same source.
- **Forecast color and category**: the forecast API's `color` and `aqi_category` are the AQI
  scale level's color and label, computed from `aqi_value`; the stored `aqi_category` is only
  for the admin.
- **Catalog** (`meta/datasets/`): each entry type has `display` hints (`precision`, `chart`,
  `y_min`); `burn-status` is an entry type of the forecasts dataset.
  Each dataset has a `places_url` (`''` when none). `settings.MONITOR_OPT_IN_TYPES`
  (`{'cimis': 'weather'}`) holds types left out of `MONITOR_ENABLED_TYPES` that
  `monitors/?dataset=<id>` still lists (non-hidden, then `MonitorFilter`); `air-quality` is
  the default list, any other value is a 400, and responses without `dataset` are unchanged.
  `places_url` for `weather` and `air-quality` points there.
- **Place endpoints** `calheatscore/place/` and `forecasts/place/` take `?region_type=&region=`
  (code; retired regions answer, land use is refused) or `?monitor=` (hidden monitors 404). Heat returns the highest
  score per date among the ZIPs the place covers (a region's ZIPs need >=1% of their own area
  inside it; a monitor's is the ZIP it touches, the lowest code on a shared edge; ties go to
  the lowest ZIP code). Forecasts return the SJVAPCD zone's latest-issued row per date plus
  the `rule` that picked it: `county`, `zone`, `center` (zone holding the point-on-surface or
  monitor), or `overlap` (largest shared area). Both are
  resolved and cached 24h in `camp/apps/regions/resolve.py` (geometry-free Regions). The
  `overlap` rule needs the zone to hold >=1% of the place's own area. **Deploy:** run
  `import_forecast_zones` before deploying the place endpoints, or clear the cached
  `forecast_zone_for:` keys after the import; otherwise places answered without the 3
  custom zones keep that answer for up to 24h.
  `monitors/weather/place/` (same addressing) lists weather-dataset stations active within
  `MONITOR_ACTIVE_WINDOW_DAYS`: inside the place first (distance 0, `inside`, by distance from the
  point-on-surface), then up to 5 within 25 miles by distance from the edge, and at least the
  nearest one when the place has a boundary and any station is active; `distance` in miles;
  selection (empty included) cached 24h in `resolve.py` (`weather_stations_for`), rows serialized
  fresh, so a station hidden since then is dropped and the list can be shorter for up to 24h.
  `hms/smoke/place/` takes the same place params plus `date__gte`/`date__lte` (Pacific dates;
  both: that range; only `date__gte`: through today; only `date__lte`: the 30 days ending
  there; neither: the last 30 days; at most 366 days, else 400, as is gte after lte). It
  returns one row per day: `density` is the heaviest `smoke-density` key (`light`, `medium`,
  `heavy`) or `null`; `coverage` is the share of the place's area under at least each level
  (0 or 1 for a monitor). Computed on request in `camp/apps/hms/place.py`, measured in
  EPSG:3310. A day is settled at 22:00 UTC the next day (an hour after `fetch_smoke_final`);
  a settled range is cached 24h server-side and sent `public, max-age=86400`, any other
  200 `max-age=900`, errors `no-cache`. A day with no outlines can't be told from a missed
  fetch (deferred).
- **Pesticide place** `pesticides/place/` takes the same addressing (`?region_type=&region=` or
  `?monitor=`) and returns `months` and `years` from `PesticideUseRollup`: counties by
  `county=`, other regions by the MTRS sections they touch, monitors by their ZIP. Month 0
  (undated records) appears only in `years[].undated` and is included in the year totals.
  Acres and applications count each record once: per-ingredient columns with `chemical`,
  MAX per record key (product, commodity, method, section, month) with `category`/`iarc_group`,
  `records`/`acres_once` otherwise (product, commodity, method, any `narrow`; `counting_mode`
  in the endpoint). Placeholder chemicals (UNKNOWN, AI IS CONFIDENTIAL) carry no pounds; their
  records count in applications and acres. Optional filters:
  - `chemical`, `commodity`, `product`: our sqids (the list endpoints' `id`), never CDPR
    codes. Sqids can be all digits, so a code can't be told from an id. A value that isn't
    an id is a 400 with code `invalid`; a well-formed id with no row is `not_found`.
  - `category`: repeated or comma-separated, any of them (OR). `narrow`: one of `concern`,
    `restricted`, `fumigant`, `aerial` (`stats.narrow_rows`; restricted and fumigant are
    product properties, unlike the same-named categories).
  - `iarc_group`, `aerial_ground` (`none` = not reported), `year__gte`, `year__lte`
    (1900-2100).

  Bounds are enforced, and an invalid value is a 400 whose field errors carry `invalid`
  (`no-cache`, as are place errors). 200s are `public, max-age=3600`. Answers
  are also cached server-side for 24h under the pesticides data version (an import retires
  them), with the filters hashed into the key. A monitor outside every ZIP gets empty lists.
- **Regions**: `regions/?within=...&within_mode=overlaps` (also the geojson variant) keeps
  regions with >=1% of their own area inside the parents and adds `also_in`; the default
  `contained` mode is unchanged. `regions/meta/` types carry `label_plural` (`Region.TYPE_LABELS_PLURAL`,
  Title Case like `label`), `name_template` (`Region.TYPE_NAME_TEMPLATES`: how to show a region,
  with `{name}` once: `"ZIP {name}"`, `"Census Tract {name}"`, `"{name} Urban Area"`,
  `"{name} AB 617 Community"`; `null` for types shown by their plain name; region rows don't
  carry it), `count`, `parents`, `referenceable` (false for land use) and
  `browsable` (false for MTRS and land use).
  `regions/meta/` also lists `buffers` (`[{miles, label}]` from `shapes.BUFFERS` and
  `BUFFER_LABELS`): the values every `?buffer=` accepts (`regions/<id>/`, pesticide sections,
  emissions map areas). Clients read the choices from there, so change them only in `shapes.py`.
- **Place search** `regions/places/search/?q=` returns list-shaped rows (`boundary` has `bbox`, no
  geometry; the picker searches as you type) plus `county` (`{type, external_id, name}` of the
  county holding the region's point-on-surface, `null` for counties and regions outside every
  county), via `RegionQuerySet.with_county()`: one query, no per-row lookups.
- **Monitor list** `monitors/?region=<sqid>` (repeatable, a union) scopes the list with
  `scope_to`, like `at/`; blank values are ignored, an unknown id is a 404 (not cached). The
  list cache key includes it.
- **HMS lists** `hms/smoke/` and `hms/fire/` default to today (yesterday before noon) only when
  no date filter is given; any of `date`, `date__gte`, `date__lte`, `date__gt`, `date__lt` turns
  the default off, so month ranges work. Rows are ordered `-date, id`; keep a unique tiebreaker
  so paged ranges never repeat or skip rows.
- **CalEnviroScreen** `calenviroscreen/4.0|5.0/?region_id=` matches tracts that touch the
  region; `&within_mode=contained|overlaps` uses the regions list's 99%/1% area rule
  (`area_fraction_inside` in `camp/apps/regions/querysets.py`), measured on each record's own
  boundary vintage. An unknown mode is a 400.
- **Place lookup** `regions/places/lookup/` has three modes. Name: `GET ?q=` (+ `type`), the best
  match. Point: `POST {lat, lon, type?}` lists the current regions containing the point;
  coordinates are rounded to 3 decimals (server too) and only ever travel in the body. Monitor:
  `GET ?monitor=&type=`. `type` is a comma list (the POST also takes a JSON array); the
  default is every type but `land_use` and `mtrs`, and asking for `land_use` is a 400. Hidden
  monitors 404 (this also applies to the heat/forecast place endpoints); other monitors, CIMIS
  included, answer. Coordinates in a query string (`lat`/`lon`/`latitude`/`longitude`) are
  refused (400, `no-cache`) by `CoordinateQueryGuardMiddleware` (`camp/api/middleware.py`)
  before the view stack. `camp/utils/sentry.py` scrubs lookup events, and `SCOUT_URI_REPORTING='path'`
  keeps query strings out of Scout traces (site-wide). Answers are cached 24h; re-importing
  boundaries leaves stale answers until they expire.
- **Location search** `regions/locations/search/?q=` finds schools and child-care sites by name
  (typo-tolerant, and a town can be part of the query: "lincoln visalia"). `q` is stripped; under 2
  characters answers an empty 200, over 100 is a 400. Optional `type` (comma list of location
  types; names the unknown ones in its 400) and `region_type`+`region` (a code, both or neither;
  county, city, cdp, zipcode or school_district; retired regions still filter, unknown code 404).
  Returns `{data: [location rows], more}`: 10 rows, stretched to 15 while the following rows repeat
  the 10th's name; `more` is true when any match was left out. 200s are `public, max-age=3600`,
  errors `no-cache`; no server-side cache. Labels for the types come from `regions/meta/`
  `location_types`.
- **Summary cache rule** (`camp/api/v2/summaries/endpoints.py`): a 200 for a settled period is
  `private, max-age=86400`, any other 200 is `private, max-age=60`; both carry an `ETag` and
  answer `If-None-Match` with a 304 (which keeps the 200's headers). Errors are `no-cache`.
  A period is settled once its end plus `SETTLE_MARGIN` has passed (`camp/apps/summaries/schedule.py`).
  `ROLLUP_LOCAL_TIME` there holds when each rollup runs after the period ends; a test checks
  the margins against the real crontabs, so moving a rollup past its settle time fails it.
  Monitor summary rows (and the bulk rows) carry `sum`; region rows don't.
- **Rollup timing**: Huey crontabs are UTC (its `utc=True` default; `DJANGO_HUEY` doesn't
  change it), so each daily-and-longer rollup is scheduled with `pacific_crontab()`
  (`camp/apps/summaries/schedule.py`): it matches both UTC hours that can hold its Pacific hour
  (`ROLLUP_UTC_HOURS`: 01:00 Pacific is `8,9`, 02:00 is `9,10`) and keeps only the one that is
  that Pacific hour (fold 0 on fall-back day). The scheduler decides, so a rollup that starts
  late still runs; the task body only works out "last period" from the current time.
- **Summary period math** (`camp/apps/summaries/periods.py`): the one place for period
  starts, ends and hour lists. Starts are Pacific calendar dates built with `make_aware`,
  never a `timedelta` of a day or more; hours step in UTC. All summary period math lives here.
- **Hourly parents**: `hourly_monitor_summaries` (:45) and `hourly_region_summaries` (:50)
  take their hour from the schedule (`hour_for_run` in `schedule.py`), not the clock, so a late
  start still summarizes the right hour. They run at priority 110/105, above their children
  (100/90), and log a warning when they start more than 10 minutes late.
- **`repair_summaries`**: fixes daily-and-longer rows stamped off a Pacific period start and
  fills region hours missing for hours that have monitor rows. Always scoped (`--monitor`,
  `--monitor-type`, `--region`, `--region-type`; `--region-hours` needs a region scope). Run
  `--dry-run` first: it prints the spans it will delete and re-roll and the counts. Day and month
  work widens to the finished periods overlapping the range; unfinished periods are left for the
  scheduled rollup. Misaligned rows whose period it won't re-roll are left and reported.
  It deletes and re-rolls one resolution at a time from days up, so a resolution's old rows are
  missing only while it re-rolls. `--region-hours` fills only [start, end), not the widened range.
  Idempotent. Limits:
  - A misaligned row of an unfinished period (e.g. a partial current-year row) is deleted
    and nothing replaces it until that period's scheduled rollup.
  - `--region-type` covers current regions only; a retired region's rows need `--region <pk>`,
    and `check_summary_integrity` keeps reporting them until then.
  - An hour whose monitors all have weight 0 (health score 0) correctly gets no region row,
    so `--region-hours` keeps listing it as missing (and the integrity check does too when
    that is true of every region in the hour).

  ```bash
  docker compose run --rm web python manage.py repair_summaries 2026-10-01 2026-11-04 \
    --monitor <monitor-id> --region <region-pk> --region-hours --dry-run
  ```
- **`check_summary_integrity`** (02:30 Pacific, read-only): logs an error (Sentry) when summary
  rows in the last 400 days are off a Pacific period start, or when hours of the previous
  Pacific day have monitor hourly rows but no region hourly rows. Logs its run time at info.
- **Burn status** (`camp/apps/forecasts/scales.py`): the feed's `status` string is stored as
  received; unknown values are stored and logged by the ingest task. When a new value
  appears, add a level there. The "No Burning For All" string is still unconfirmed.

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
