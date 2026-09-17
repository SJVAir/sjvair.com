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
`?include_hidden=1`.

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

Slug `coverage`. Hidden monitors excluded as above. Query param
`radius` in meters, default `1000`.

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
subquery per tract. County assignment for tracts uses the in-process
county polygons in `camp/utils/counties.py` (the same ones
`Monitor.save()` uses), via centroid containment. All of this is a
handful of PostGIS queries over a few hundred monitors and a few
thousand tracts. No caching for now; add it if the page proves slow.

### 3. Fleet Health (ops)

Slug `fleet-health`. Hidden monitors are included here, in their own
column, because ops cares about them.

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

Excludes hidden monitors unless `?include_hidden=1`. Filters `?county=`
and `?type=` (monitor type slug).

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
- Data volume and host roster reports (candidates for the next batch).
