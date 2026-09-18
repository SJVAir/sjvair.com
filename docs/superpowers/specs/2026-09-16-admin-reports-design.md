# Admin Reports — Design

**Date:** 2026-09-16
**Branch:** `feature/admin-reports`
**Audience:** CCAC staff, from the tech/ops side through to the Executive Director.

## Goal

A small set of staff-only report pages in the Django admin that answer
recurring questions without anyone writing a query. Two of the first
four are for the ED (numbers for conversations and presentations), two
are for ops (what is broken right now). The existing "Subscription Stats
by County" page moves into the same structure so all reports live in
one place.

Alerts and subscriptions are otherwise out of scope; that system has a
separate rework pending.

## Structure

New app `camp.apps.reports`. No models, no migrations.

```
camp/apps/reports/
    __init__.py
    apps.py
    base.py          # BaseReport view + registry
    views.py         # ReportIndex + the concrete reports
    urls.py
    tests.py
camp/templates/admin/reports/
    index.html
    base.html        # shared chrome: breadcrumbs, title, filters
    network_overview.html
    coverage.html
    fleet_health.html
    degraded_monitors.html
    subscription_county_stats.html   # moved from admin/alerts/subscription/
```

### `BaseReport`

A `vanilla.TemplateView` wrapped in `staff_member_required`, following
the existing `SubscriptionCountyStats` view. Class attributes:

- `slug` — URL segment and registry key
- `title` — page heading and index link text
- `description` — one line under the title on the index page
- `template_name`

Methods:

- `get_rows()` — returns a list of dicts. Required. This is the
  primary table.
- `get_context_data()` — supplies `admin.site.each_context(request)`,
  `title`, `rows`, `report` (the view instance), and anything a
  subclass adds for summary tiles or secondary tables.

Reports that have more than one table (network overview, fleet health,
coverage) expose the primary table via `get_rows()` and the secondary
tables via named context keys. There is no CSV export; the pages are
read on screen.

### Registry and URLs

`base.py` holds `REPORTS = []` and a `register(cls)` decorator that
appends to it. `urls.py` builds one `path(f'{cls.slug}/', cls.as_view(),
name=f'reports-{cls.slug}')` per registered report plus the index at
`''`. Included from `camp/urls.py` at `batcave/reports/` under the
`reports` namespace, alongside the existing `batcave/stats.json` and
`batcave/flush-queue/` routes. Because the views are wrapped in
`staff_member_required` and render with the admin site context, they
look and behave like admin pages without needing a `ModelAdmin` to hang
off.

### Admin index

The Quick Links block in `camp/templates/admin/index.html` becomes a
"Reports" block listing every registered report by title, fed by a
`report_list` simple tag in the `reports` template tag library.

### Moving county stats

`SubscriptionCountyStats` moves from `camp/apps/alerts/views.py` to
`camp/apps/reports/views.py`, subclassing `BaseReport`, behavior
unchanged. The `get_urls` override in
`SubscriptionAdmin` is replaced by a `RedirectView` under the same
`alerts_subscription_county_stats` URL name pointing at the new page,
so existing bookmarks keep working. The old template is moved, not
duplicated.

## Reports

### 1. Network Overview (ED)

Slug `network-overview`. Hidden monitors are excluded unless
`?include_hidden=1`; `?sjvair_only=1` restricts to SJVAir-owned monitors
(off by default).

**Tiles:** total monitors, active in the last hour, SJVAir-owned
(`is_sjvair`).

**Primary table (rows):** one row per monitor type (the enabled
subclasses from `Monitor.get_subclasses()`, ordered by display name)
with a column per SJV county plus a total. Values are monitor counts.
A final "All types" row sums the columns.

No deployments-over-time table: `Monitor.created` records when the row was
registered, often months before the device is actually installed, so it is
not a meaningful deployment date.

Queries: one `aggregate()` over `Monitor` for the tiles, one
`values(type, county).annotate(Count)` for the matrix (type derived via
the existing `with_grade`-style `Case` over subclass joins, or by
iterating subclasses and issuing one small count each; either is fine,
pick whichever reads cleaner).

### 2. Coverage and Equity (ED)

Slug `coverage`. Hidden monitors excluded as above. Only monitors active
in the last hour count toward coverage unless `?include_inactive=1`; a
dead monitor covers nobody. `?sjvair_only=1` restricts to SJVAir-owned
monitors (off by default: coverage is about what the public map shows).
Query param `radius` in meters, default `1000`.

**Primary table (rows):** one row per SJV county:

- monitors
- population (sum of CES tract population for tracts whose boundary
  centroid falls in the county)
- monitors per 10k residents
- DAC tracts (count with `dac_sb535=True`)
- monitors located in a DAC tract
- DAC population within `radius` of any monitor, and as a share of the
  county's DAC population

Plus a totals row.

**Secondary table `percentile_bands`:** CES score percentile bands
(0–25, 25–50, 50–75, 75–100) with tract count, population, monitors in
those tracts, and monitors per 10k.

**Data source:** the newest CES version present in the database.
Determined by ordering `Boundary` rows that have a CES record by
`version` descending and taking the first; the CES model class (`CES4`
vs `CES5`) follows from which one has records for that version. Tract
boundaries live in `regions.Boundary` with `Region.type == 'tract'`.

**Spatial work:** monitor-in-tract is `Boundary.geometry.contains(
monitor.position)`; "within radius" is a `dwithin` between the tract
geometry and a union of monitor points, or equivalently an `exists`
subquery per tract. County assignment for tracts uses centroid
containment in the county `Region` boundaries
(`Region.objects.counties()`); a county with no Region row shows zero
population. All of this is a
handful of PostGIS queries over a few hundred monitors and a few
thousand tracts. No caching for now; add it if the page proves slow.

### 3. Fleet Health (ops)

Slug `fleet-health`. Hidden monitors are included here, in their own
column, because ops cares about them. Shows only SJVAir-owned monitors
unless `?sjvair_only=0`.

**Primary table (rows):** one row per monitor type with columns:

- active (last entry within 1 hour)
- silent 1–24 h
- silent 1–7 d
- silent over 7 d
- never reported
- hidden

Bucketing uses `with_last_entry_timestamp()` and a `Case` on the
annotation. Filter `?county=` narrows to one county.

**Secondary table `grades`:** for monitor types where
`supports_health_checks()` can be true, the count of monitors whose
current `monitor.health` has grade A, B, C, F, plus "no check" for
monitors with no linked health check. Uses `Monitor.health__score`.

### 4. Degraded Monitors (ops)

Slug `degraded-monitors`. Flat list, one row per monitor that meets any
of:

- current health grade C or F (`health__score__lte=1`)
- current health check has `sanity_flatline_a` or `sanity_flatline_b`
  set to `False`
- last entry older than 24 hours (including never reported)

Excludes hidden monitors unless `?include_hidden=1`, and shows only
SJVAir-owned monitors (`is_sjvair`) unless `?sjvair_only=0`. Filters
`?county=` and `?type=` (monitor type slug).

Columns: monitor name linking to its admin change page, type, county,
host, grade, last seen, condition (a short label: "Grade F",
"Flatline A", "Silent 3d", etc., joined if several apply).

Sorted worst first: silent monitors by longest silence, then grade F,
then C, then flatline-only.

Queries: one queryset with `with_last_entry_timestamp()`,
`select_related('health', 'host')`, and a `Q` for the conditions. Type
and admin URL are derived in Python per row from the subclass, which is
fine for a list in the low hundreds.

## Templates

All report templates extend `admin/reports/base.html`, which extends
`admin/base_site.html` and provides breadcrumbs (Home › Reports ›
Title), the title, the description, and a block for filters. Tables use
the admin's default table styling as the county stats page does. No
JavaScript, no charts.

## Testing

`camp/apps/reports/tests.py`, Django `TestCase`, plain `assert`,
fixtures from `/fixtures` where they fit (`purple-air.yaml`,
`regions.yaml`, `calenviroscreen.yaml`, `users.yaml`), supplemented in
`setUp` with monitors and health checks created directly.

- Index page lists every registered report and requires staff.
- Old county stats URL redirects to the new page; the new page returns
  the same rows as before.
- Each report: HTML 200 and a
  handful of value assertions (e.g. a monitor placed inside a DAC tract
  counts as in-DAC; a monitor with no entries lands in "never
  reported"; a monitor with score 0 appears in degraded with condition
  "Grade F").
- Filters: `include_hidden`, `county`, `type` each toggle a known row.

## Out of scope

- Alerts and subscription growth (pending rework).
- Caching.
- Charts or any client-side rendering.
- Data volume and host roster reports (candidates for a later batch).

## Batch two (2026-09-17)

Four more reports were built on the same branch and PR, using `BaseReport`
unchanged. After trying them, Derek kept only Coverage by Community (§5,
grouped with the ED reports on the index) and removed Data Completeness,
Data Quality Problems, and Pipeline Coverage on 2026-09-18 as not telling
staff much. Their sections (§6–8) are kept below for the record; the code
is gone.

Shared conventions from batch one carry over: `?sjvair_only=1|0` (ED
reports default off, ops reports default on with the hidden-input
pattern), `?include_hidden=1`, `?county=<name>`, `Outside SJV` for a
blank or non-SJV county, totals rows in `<tfoot>`, admin change-page
links via `DegradedMonitors.admin_url`-style fail-soft reverse.

### 5. Coverage by Community (ED)

Slug `coverage-community`. One row per city and CDP `Region`
(`Region.Type.CITY`, `Region.Type.CDP`) that has a current boundary:
name, type ("City" / "CDP"), county (the county Region containing the
place's centroid, via `Region.objects.get_county_region`, or the
in-process `County.lookup` fallback if that is simpler; report which),
population, monitors, monitors per 10k, and for places with no monitor
the distance in km to the nearest counted monitor.

- Population is the sum of CES tract population for tracts (newest CES
  version present, same rule as Coverage) whose centroid is inside the
  place boundary. Places with no tract centroid inside them show the
  population of the tract containing the place centroid instead, so
  small CDPs are not reported as zero-population.
- Monitors counted are the same set as Coverage: positioned, enabled
  types, not hidden unless `?include_hidden=1`, active in the last hour
  unless `?include_inactive=1`, SJVAir-only when `?sjvair_only=1`.
  A monitor counts for a place when its position is inside the boundary.
- Nearest-monitor distance uses `Distance` between the place centroid and
  the nearest counted monitor, one indexed query per uncovered place.
- Filters: `?county=` (the place's county), `?place_type=city|cdp`,
  `?min_population=`, and `?uncovered=1` (only places with zero monitors).
  The tiles follow the scoping filters but ignore `uncovered`.
- Every column header sorts: `?sort=<column>&dir=asc|desc`, clicking the
  active column flips it; rows with no value for the column sort last.
  Default is population descending.
- Each place links to its Region admin change page, where type-specific
  panels (below) show the detail. Containment for coverage uses the place
  boundary with its holes filled (`camp.utils.gis.fill_holes`): a county
  island inside a city is part of that community. Monitor counts and
  tract-centroid assignment run in Python over spatial indexes
  (shapely `STRtree`) from two queries, not per-place SQL.
- Urban areas are excluded from the list (they overlap cities and CDPs)
  but get the same panel on their own admin page.

### Region admin panels

`camp/apps/regions/panels.py` holds a registry of `Panel` classes keyed by
region type; `RegionAdmin.change_view` passes `panels_for(region, request)`
to `admin/regions/region/change_form.html`, which renders each panel's
template under the fields. Apps register their own panels on import
(`ReportsConfig.ready` imports `camp.apps.reports.panels`). Scope toggles on
a panel are links (the admin change page cannot host a second form),
built by `MonitorScope.toggle_links`, so the numbers agree with the
Coverage by Community report under the same toggles.

- **Coverage** (city, CDP, urban area; `camp.apps.reports.panels`):
  population from CES tracts, counted monitors under the scope, per 10k,
  nearest counted monitor when uncovered, CES tract stats (count, DAC
  count, DAC population, average and highest percentile), monitor status
  counts, and every monitor inside with admin links. Holes filled, with a
  note when the boundary has any.
- **Communities and coverage** (county): the Coverage by Community rows
  for that county with tiles, plus the county's monitors.
- **CalEnviroScreen** (tract; `camp.apps.regions.panels`): every CES4/CES5
  record on the tract's boundaries, newest first, as field tables, plus
  the monitors inside.
- **Monitors inside** (zipcode, school district, legislative districts,
  protected areas, land use, place, custom, MTRS): status counts and the
  monitor list.

### 6. Data Completeness (ops)

Slug `data-completeness`. Uses `MonitorSummary` rows at
`Resolution.DAILY`, RAW processor (`processor=''`), for one entry type
(`?entry_type=`, default `pm25`; choices are every entry type with any
daily summary). "Expected" is the summary's own `expected_count`.

- Primary table: one row per monitor type with received, expected, and
  percent for the last 7 days and the last 30 days (calendar days ending
  yesterday, Pacific time, so today's partial day does not drag the
  number down), plus a monitor count.
- Secondary table `low`: monitors whose 7-day percent is below
  `?threshold=` (default 80) with type, county, host, received, expected,
  percent, and admin link; worst first. Monitors with no summary rows in
  the window appear with 0 received and are listed first.
- Filters `?county=`, `?sjvair_only` (default on), `?include_hidden=1`
  (hidden excluded by default, unlike Fleet Health, because this is
  about live data quality).

### 7. Data Quality Problems (ops)

Slug `data-quality`. Every subclass, hidden included. One row per monitor
failing any check, with a `condition` column joining the labels:

- `No position` — `position` is null.
- `Bogus position` — outside the fallback valley box used by the maps,
  including (0, 0).
- `No name` — blank `name`.
- `No county` — blank `county` but the position is inside some SJV county
  Region boundary (a monitor legitimately outside the valley is not
  flagged).
- `Wrong county` — `county` set but the position is not inside that
  county's Region boundary.
- `Hidden but reporting` — `is_hidden` and a `LatestEntry` within
  `Monitor.LAST_ACTIVE_LIMIT`.
- `No host` — `is_sjvair` and `host` is null.

Sorted by the first failing check in the order above, then name. Columns:
name (admin link, or the pk when the name is blank), type, county,
position as "lat, lon" to 4 places, condition. Filters `?type=` and
`?county=` (county filter matches the stored field). Tiles: total
flagged, and a count per condition.

County containment uses the county Region boundaries only; monitors are
tested with one `Exists` per check where possible, and never one query
per monitor.

### 8. Pipeline Coverage (config)

Slug `pipeline-coverage`. No filters. A matrix of enabled monitor types
(rows) against every entry type any of them produces (columns, from
`Monitor.ENTRY_CONFIG` keys, ordered by `entry_type`). Each cell:

- blank when the type does not produce that entry type;
- otherwise the stages the config allows (`allowed_stages`, e.g.
  "RAW → CLEANED"), the default stage, and one of:
  - `published: <calibration or default stage>` when a
    `DefaultCalibration` row exists for the pair;
  - `not published` when data is produced but no row exists.

Below the matrix, a list of `DefaultCalibration` rows whose
(monitor type, entry type) pair no enabled type produces ("orphaned
publish rows"), and a count of pairs produced but unpublished. The
`rows` payload for the base class is the matrix (one dict per type, one
key per entry type holding the cell label), so the page renders through
the same template pattern as Network Overview.

### Testing (batch two)

Same file and conventions. Coverage by Community uses `regions.yaml`
(it has a Fresno city region with a real boundary) and
`calenviroscreen.yaml`; Data Completeness creates daily `MonitorSummary`
rows directly; Data Quality creates monitors that trip each check exactly
once, including one legitimately outside the valley that must not be
flagged; Pipeline Coverage loads `default-calibrations.yaml` and asserts
on PurpleAir PM2.5 (published) and a produced-but-unpublished pair.
