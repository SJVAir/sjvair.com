# Metadata enablers (Release 1, step 3, first batch)

Date: 2026-10-22. Repos: sjvair.com (branch `feature/metadata-enablers` from `develop`, PR
into `develop`) and sdk-js (feature branch, PR into `main`).

## Why

The new SJVAir dashboard (`~/workspace/sjvair/data-dashboard`) follows one rule: anything
that describes data (labels, units, resolutions, coverage, which pollutants are offered)
comes from server metadata, never hardcoded in the client. Its data layer (Foundations
spec 2, being built now) needs three things from the server that don't exist yet:

1. a **dataset catalog** that says what data exists, and an **available-pollutants** gate;
2. **regions and locations referenced by official code** (county FIPS, ZIP, CDS code, …),
   because the server's `sqid` ids differ between local dev, staging, and production and
   change on re-import, while saved dashboards and alert rules hold references for years;
3. a **coverage endpoint** saying what date range of data exists.

Until (2) ships, the dashboard reports region queries as "unavailable". Background and the
decisions behind this live in data-dashboard: `ARCHITECTURE.md` → "Metadata as source of
truth" (including "Stable ids and retirement"), `ROADMAP.md` → Release 1 step 3, and
`docs/reference/server-data-inventory.md`. The data-dashboard session has already recorded
the format decisions below in its `ARCHITECTURE.md` (commits 3960cd6 and 2b0d00c).

Build order: catalog and available pollutants, then region and location codes (with
permanence), then coverage. The sdk-js work follows each server piece.

## Goals

- `meta/datasets/` lists every data domain the server has, in the agreed format.
- One switch turns a pollutant on for the map, dashboard widgets, analyses, and alerts.
- Regions and locations can be looked up by their official code; responses carry the code.
- Codes are **permanent**: once a code has been published it always resolves, to the
  current row or to a row marked retired (with a replacement where there is one).
- A cheap coverage endpoint for one dataset or one place.
- sdk-js wrappers for all of the above, plus a time-zone bug fix.

## Non-goals

- Scale metas (smoke, fire, CalHeatScore, AQI), shared action tiers, region hierarchy,
  choice lists, display hints, cache headers on summaries, `places/lookup/` by
  coordinates, location name search: later step 3 work.
- "Retired" vs "never existed" for **monitors** (not in this round).
- Code lookup and permanence for **land-use regions** (unstable codes; see section 3).
- Greying out places with no data in the dashboard's place picker (deferred; it would need
  a bulk coverage mode, recorded in data-dashboard's `DEFERRED.md`).
- Any change to the dashboard itself.

## Anti-goals (failure even if it works)

- **New ongoing server load.** No background task or precomputed table for coverage; every
  coverage answer must come from an indexed lookup or a small handful of queries, cached.
- **A second pollutant switch** that can drift out of sync with what the map shows.
- **A published code that later stops resolving or points at something else.**
- **Closed schools or retired regions leaking into existing listings** (the Pesticides
  Explorer, Facility Emissions Explorer, place search, summaries) after permanence lands.
- **Breaking existing sdk-js callers** (monitor-map, mobile) with the time-zone fix.

## 1. Dataset catalog: `GET /api/2.0/meta/datasets/`

A new top-level `meta/` URL namespace. The response lists every domain the server has,
whether or not the dashboard can display it yet (the dashboard hides entries it has no
adapter for):

`air-quality`, `weather`, `hms-smoke`, `hms-fire`, `pesticide-use`, `pesticide-notices`,
`forecasts`, `calheatscore`, `calenviroscreen`, `emissions`, `tempo`.

Each entry (JSON keys in the server's usual snake_case; the SDK exposes them as typed):

```ts
{
  id: string;            // permanent; never reused or renamed
  label: string;
  description: string;
  source: string;        // e.g. "SJVAir sensor network, EPA AirNow, CARB AQview"
  license: string;       // attribution text
  entry_types: {
    id: string;          // permanent; for monitor data, the server's entry_type key ("pm25")
    label: string;
    kind: "pollutant" | "meteorological" | "other";
    units: string;
    resolutions: ("raw" | "hour" | "day" | "month" | "quarter" | "season" | "year")[];
    available?: boolean; // air-quality pollutants only; see section 2
    retired?: { since: string; replaced_by?: string } | null;
  }[];
  geographies: ("monitor" | "region" | "polygon" | "point" | "tract" | "zip" | "zone")[];
  meta_url: string;      // the domain's own …/meta/ endpoint, or "" if none yet
  retired?: { since: string; replaced_by?: string } | null;
}
```

Plus one static, catalog-level fact: **monthly and longer summaries exist only after the
period ends** (a short machine-readable field, e.g. `summary_rules`; exact shape is the
builder's call). This replaces any per-place "which resolutions are complete" data.

Decisions:

- **Resolutions are listed per entry type**, and there is **no dataset-level
  `resolutions` field** (decided with the user; the client never needs an inheritance
  rule). For air quality, the resolutions come from the code: entry types that are
  summarized (today pm25, o3, no2, so2, co) list `raw` plus every summary resolution;
  others (pm10, …) list `raw` only. Derive this from the summaries app's own list rather
  than a second hardcoded copy.
- **Ids are permanent and never reused.** A rename changes `label`, never `id`. State this
  in the endpoint's docstring and the API docs.
- `retired` is part of the format from day one; nothing is retired at launch.
- `meta_url` is set for domains that have a meta endpoint today (`monitors/meta/` for
  air quality and weather, `regions/meta/` where relevant) and `""` for the rest until
  their scale metas land.
- **Air quality vs weather:** `weather` is the CIMIS monitor type's entry types;
  `air-quality` is the other monitor types' entry types. _My call:_ meteorological entry
  types reported by air-quality monitors (e.g. PurpleAir temperature and humidity) are
  listed under `air-quality` with `kind: "meteorological"`, since that's where the data
  lives; weather stays CIMIS-only.
- Entry types for the non-monitor domains (smoke density, fire FRP, pesticide pounds and
  acres, heat score, CalEnviroScreen indicators, emissions, TEMPO products) are the
  builder's call, based on what each domain's endpoints actually return. Keep ids
  lowercase, stable, and descriptive.
- Mostly static: cache it (process-level or Django cache, plus HTTP `Cache-Control` of
  about an hour). Only `available` depends on database rows.

## 2. Available pollutants

Derived from the existing **`DefaultCalibration`** rows (admin-editable, loaded from
`fixtures/default-calibrations.yaml`), which already decide which (monitor type, entry
type) pairs appear on the map and which `monitors/meta/` reports as `published`.

- An air-quality pollutant is **available** if any enabled monitor type publishes it.
  Today: pm25 and o3.
- Exposed as `available` on each air-quality entry type in the catalog, and as an
  `available_pollutants` list on `monitors/meta/` (for code that reads only that endpoint).
- **One switch, everywhere at once** (decided with the user): adding a `DefaultCalibration`
  row for NO2 shows it on the map and offers it in widgets, analyses, and alerts. There is
  no separate dashboard-only switch.
- The catalog's cache must not hide an admin change for long: invalidate on
  `DefaultCalibration` save/delete, or keep that part uncached (builder's call).

## 3. Region and location codes, with permanence

### What exists today (verified 2026-10-22)

- `Region` is unique on `(type, external_id)`; every region import upserts by that pair
  through `Region.objects.import_or_update` and **never deletes or recodes a region**.
  Locally every region has a non-empty code, including the 3 `custom` forecast zones
  (`sjvapcd-kern-airbasin`, `sjvapcd-tulare-valley`, `sjvapcd-sequoia`).
- `Location` is unique on `(source, external_id)`. `camp/apps/regions/locations.py`
  `import_source` **deletes** rows missing from the latest file.
- Child-care licenses at one name and address merge into one row keyed by the **lowest
  facility number** (`locations.py`, the `sites` loop), so the code changes if that license
  closes.
- `LocationQuerySet.one_per_place()` groups nearby same-name child-care rows at read time
  and picks the **lowest pk** as representative, which differs between environments.
- The region API returns `id` (sqid), name, slug, type, and boundary, but not
  `external_id`. Locations have no endpoint outside `pesticides/locations/`.
- Production is missing the 3 `custom` forecast-zone regions.

### Which types the promise covers

**Land use is excluded** (decided with the user). `import_land_use` builds its code as
`{County}-{jurisdiction}-{OBJECTID}`, and a refresh of the CKAN dataset can renumber
`OBJECTID`s, so a saved code could silently point at a different area. Until a stable
code is built from fields that survive a refresh:

- lookup by code refuses `type=land_use` with a clear 400 message;
- land-use regions still return `external_id` in responses, and the API docs say it is
  not a permanent code;
- land use isn't on the dashboard's Release 1 list, so nothing references it yet.

Every other region type is covered: county, city, cdp, zipcode, tract, school_district,
congressional_district, state_assembly, state_senate, air_district, urban_area,
protected, ab617, mtrs, custom (forecast zones), plus all location sources. Census tracts
are fine: a tract GEOID is stable, and a tract with only a 2010 boundary is still a valid
reference to that tract (_my call_: no automatic retirement of 2010-only tracts).

### API changes

- **Every region response** (list, detail, GeoJSON feature properties, `places/search/`,
  `places/lookup/`) gains `external_id` and `retired`:
  `retired: { since: "YYYY-MM-DD", replaced_by: { type, external_id } | null } | null`.
- **Region lookup by code:** a filter on the region list,
  `GET regions/?type=county&external_id=06019,06107` (comma-separated, several codes per
  call; requires `type`). Each result includes its `id` (sqid), which the client uses for
  summary URLs, so summary routes don't change. A retired region **is returned**, flagged.
  A code that never existed is simply absent. Cap the number of codes per call (builder's
  call; generous).
- **Location lookup by code:** new `GET regions/locations/?source=cdss-ccl&external_id=…`
  (same comma-separated rule), returning the location with `source`, `external_id`,
  `type`, name, point, its region links (as type + code), and `retired`. Later location
  name search can live on the same route.
- Region detail by sqid keeps working for retired regions.

### Permanence

- `Region` and `Location` gain `retired_at` (date, nullable) and `replaced_by` (nullable
  self-FK, `SET_NULL`). Migration only; no backfill needed.
- **Locations are retired, not deleted.** `import_source` marks rows missing from the file
  retired (keeping the existing "an empty parse removes nothing" guard), and un-retires a
  row that reappears. Codes stay occupied, so they're never reused.
- **Child-care codes are sticky.** When a parsed site's facility numbers include an
  existing row's code, or overlap that row's stored `facility_numbers`, the site keeps the
  existing row's code, even after that license closes. A lookup by **any** facility number
  at a site resolves to the site. How the alias lookup is done (a JSON containment query on
  `metadata.facility_numbers`, or a small alias table) is the builder's call; the alias
  table is the safer choice if a site can split.
- **`one_per_place()` picks the lowest `external_id`**, not the lowest pk, so the
  representative is the same in every environment.
- **CDP becomes a city:** the Census usually keeps the place's GEOID. When `import_cities`
  creates or updates a city whose GEOID matches an existing `cdp` row, it retires the CDP
  with `replaced_by` set to the city. Also handle the reverse defensively (no automatic
  retirement if the match is ambiguous).
- **Other region types are not retired automatically**, since imports can be limited to
  some counties, so a missing row doesn't mean the region is gone. Staff can retire or
  un-retire a region (and set `replaced_by`) in the Django admin.
- **Import commands never change an existing code.** Add a test that pins this for the
  region manager and the location importer.

### Keeping retired rows out of existing features

Retired rows stay in the tables, and about 80 files query `Region` or `Location` (the
Pesticides Explorer, Facility Emissions Explorer, SprayDays notices, audits, summaries,
place search, map config, CES/HMS/TEMPO/pesticide filters, …). Agreed approach:

- **`Region.objects` and `Location.objects` hide retired rows by default**; a second
  manager (e.g. `all_objects`) includes them.
- **Rule: listings and searches show current rows only; anything that names a specific
  region or location (by code or by sqid) finds it, retired or not.**
- Use the include-retired manager in: the new code lookups; region detail by sqid; the
  filters that take a region id (CES, HMS, TEMPO, pesticides, summaries), so old URLs keep
  working; the Django admin (with a retired filter and un-retire action); and the import
  commands (so they update a retired row instead of creating a duplicate).
- Django's default-manager semantics are easy to get wrong (admin, related lookups,
  `_base_manager`, migrations). **Review every call site**, don't assume. Tests assert that
  each listing skips a retired row and each by-id path still finds one.
- Changing `one_per_place()`'s representative can change cached results: bump the
  Emissions Schools tab `CACHE_VERSION` and any pesticide place caches that include
  location rows.

### Deploy steps (in the PR description)

1. Migrate.
2. On production, run `import_forecast_zones` (the 3 `custom` zones are missing there).
3. No other data step: existing rows are all current, and codes are unchanged.

## 4. Coverage: `GET /api/2.0/meta/coverage/`

Computed on request and cached; no background task, no new table, no all-places mode
(decided with the user to avoid extra server load).

- **Per dataset:** `?dataset=air-quality` → `{ first: "YYYY-MM-DD", last: "YYYY-MM-DD" }`.
  A handful of queries in total across all domains; cache about an hour.
- **Per place:** `?dataset=air-quality&entry_type=pm25` plus **one** of
  `monitor=<monitor id>` or `region_type=<type>&region=<external_id>` (regions by code, so
  the dashboard skips a lookup) → `{ first, last }` for that place and entry type, or
  `null`s if there's no data. Cache about 15 minutes.
- Dates are **Pacific calendar dates**.
- Cheap by construction:
  - monitor first date: `MIN(timestamp)` on the entry table, served by the
    `(monitor, timestamp, …)` unique index; last date from `LatestEntry`;
  - region first/last: `MIN`/`MAX` on `RegionSummary` via its
    `(region, entry_type, resolution, timestamp)` unique index (hourly resolution).
  - Verify each query plan with `EXPLAIN` on a realistically sized table; the production
    entry tables are much larger than local.
- **What counts as data** (_my call_): for a published (monitor type, entry type) pair,
  a monitor's first/last count the published processor's entries (the
  `DefaultCalibration` processor, i.e. what the map and dashboard show), with `LatestEntry`
  for that processor giving `last`; for unpublished pairs, any stage. Region first/last
  come from `RegionSummary`.
- **Dataset level** (_my call_): for air quality, `entry_type` is optional; without it the
  span covers the available pollutants. It is computed from `MonitorSummary` hourly rows
  (index on `resolution, timestamp`) and `LatestEntry`, **never** a table-wide
  `MIN(timestamp)` on an entry table (those have only a BRIN index and would scan the
  production tables). So dataset `first` means "first summarized hour", which is
  acceptable. Entry types without summaries (e.g. pm10) need `entry_type` plus a place.
- No per-resolution breakdown; the "monthly+ only after the period ends" rule is in the
  catalog (section 1).
- Other domains in per-place mode are not required this round; return 400 with a clear
  message for unsupported combinations.

## 5. sdk-js

One sdk-js feature branch, PR into `main`, built after the matching server pieces exist
on local sjvair.com. **No release without the user's explicit approval for that release.**

- `getDatasetCatalog()` with types; `availablePollutants` on the monitors meta type.
- Region and location types gain `external_id` and `retired`; new wrappers for region
  lookup by code (several codes at once) and location lookup by code.
- `getCoverage()` for both modes.
- All new functions take the 4.7.0 request options (`signal`/`init`).
- **Time-zone fix** (reported by the data-dashboard session): `apiDateFormat`
  (`lib/datetime/api_date_format.ts`) formats `timestampGte`/`timestampLte` with the
  device's local clock and no offset, and the server's `TimezoneDateTimeFilter`
  (`camp/api/v2/filters.py`) reads zone-less values as Pacific, so for viewers outside
  Pacific time the raw-entry window is off by hours (monitor-map and mobile are affected
  too). Also, `getValidDate` throws when a bound is later than now, which rejects "end of
  today". Fix: send zone-aware bounds (ISO 8601 with an offset, or UTC `Z`), URL-encoded
  (`+` in a query string). The server already converts aware values to UTC; confirm its
  form field parses offsets, with a server test. Allow future bounds.
  **Whole days stay Pacific days** (_my call_, per the platform's Pacific-time
  convention): `getValidDateRange` snaps to day boundaries in `America/Los_Angeles`, not
  the device's zone, so a viewer in New York gets the same windows monitor-map and mobile
  show today; only the exact instants become correct. The `at/` endpoint's `timestamp`
  (`getMonitors({ timestamp })`, also via `apiDateFormat`) gets the same zone-aware
  treatment. Keep the exported
  `apiDateFormat` signature working for existing callers (add a new function, or keep the
  old output where it's used for display) and note the change in the changelog.
- Fix `api-urls.md` entries touched by this work.

## Testing

Per the repo's conventions (`django.test.TestCase`, pytest-style asserts, fixtures in
`/fixtures/*.yaml`):

- catalog: shape, every domain present, per-entry-type resolutions (pm25 summarized, pm10
  raw only), `available` follows `DefaultCalibration` (adding a row flips it, cache
  included);
- region/location codes: responses include codes; lookup by several codes; retired
  returned and flagged; unknown absent; sqid detail works for retired; `land_use` lookup
  refused;
- permanence: location import retires instead of deleting and un-retires; child-care
  code stays after its license closes; lookup by any facility number; `one_per_place`
  picks lowest code; CDP→city retirement; imports never change codes;
- leak checks: each listing and search skips retired rows;
- coverage: both modes, Pacific dates, empty place returns nulls, query count bounded;
- sdk-js: unit tests for each wrapper and the date fix in a non-Pacific time zone.

## Left to the builder

Endpoint module layout, the exact `summary_rules` shape, non-monitor entry type ids,
child-care alias mechanism, lookup caps, cache mechanics and durations within the
guidance above, and PR splitting (one sjvair.com PR is the default; splitting by section
is fine if it eases review).
