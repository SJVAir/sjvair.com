# Pesticides Explorer v3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Schools and child care on the map and district pages; trend charts with deltas; "chemicals of concern" as a third explorer-wide scope.

**Architecture:** A point model `regions.Location` fed by one importer with three source adapters; a GeoJSON endpoint the section map draws as markers with a 3x3-block pounds popup; a server-rendered SVG trend include fed by the existing by-year rows plus a `stats.trend_deltas` helper; and a `concern` flag threaded through `scope_param/scope_query`, `year_context`, the list/detail/records/notice views, the landing stats and the map endpoints.

**Tech Stack:** Django 5.2 + PostGIS, django-vanilla-views, django-resticus, Leaflet 1.9 + plain JS, Bulma/Sass, htmx.

**Spec:** `docs/superpowers/specs/2026-09-21-pesticides-explorer-v3-design.md` — read its **Global constraints** and the section for your task before starting.

## Global Constraints
See the spec's "Global constraints" section; they bind every task verbatim. In short: work only in the worktree `/home/derek/dev/ccac/sjvair.com/.claude/worktrees/feature+pesticides-explorer`; stage files by name; no AI attribution; do not push; Django TestCase + plain assert; sqids for new models; Bulma + htmx; products before chemicals; `Region.short_name` in tables; static assets aren't cache-busted; scope is carried by `stats.scope_param/scope_query` + `scope-hidden.html` + `year_context()`.

---

### Task 1: `regions.Location` model, migration, admin

**Files:**
- Modify: `camp/apps/regions/models.py` (add `Location`)
- Create: `camp/apps/regions/migrations/00XX_location.py` (via `makemigrations regions`; ignore the unrelated `commodities` AlterField drift on main — do not include it)
- Modify: `camp/apps/regions/admin.py`
- Test: `camp/apps/regions/tests/test_locations.py` (create the `tests/` package if `camp/apps/regions/tests.py` is a module: convert it to a package keeping existing tests)

**Interfaces:**
- Produces: `Location` exactly as in spec §1 "Model", with class methods:
  - `Location.county_for(point) -> Region | None` (county boundary containing the point, via `boundary__geometry__contains`)
  - `Location.district_for(point, cds_code=None) -> Region | None` (spec's rule: by 7-digit district code prefix on `Region.external_id` for type school_district when `cds_code` given; else the containing school-district boundary, preferring names containing "Unified", then the widest grade span from `metadata['grade_low']/['grade_high']`, else any)
  - `Location.get_absolute_url()` → the containing section's page is not this model's; return the district's pesticides region URL when `district` else `''`.
  - `Location.short_type` property: "Public school" / "Private school" / "Child care".

- [ ] Write failing tests: model saves with sqid; `county_for` returns Fresno for a point inside the fixture's Fresno square and None outside; `district_for` prefers CDS match, then Unified, then widest span; `short_type`.
- [ ] Implement model + migration + admin (`list_display = ('name', 'type', 'city', 'county')`, `search_fields = ('name', 'external_id', 'city')`, `list_filter = ('type', 'source')`).
- [ ] Run `docker compose run --rm test pytest camp/apps/regions -q`; all green.
- [ ] Commit: `feat(regions): Location model for schools and child care`.

### Task 2: `import_locations` command

**Files:**
- Create: `camp/apps/regions/management/commands/import_locations.py`
- Create: `camp/apps/regions/locations.py` (adapters + upsert + geocode cache; the command is a thin wrapper)
- Create test data: `camp/apps/regions/tests/data/pubschls-sample.txt` (8 rows: 5 keepers across 2 SJV counties, 1 Closed, 1 Virtual=F, 1 non-SJV county, 1 district row with empty School), `private-schools-sample.csv` (4 rows: 3 keepers, 1 enrollment 3), `ccl-facilities-sample.csv` (5 rows: 3 licensed centers, 1 family home, 1 Closed)
- Test: `camp/apps/regions/tests/test_import_locations.py`

**Interfaces:**
- Consumes: `Location` (Task 1); `camp.utils.geocode.resolve(address)` returning `(lat, lng)` or None (check its actual return shape in the file and adapt).
- Produces: `locations.import_source(source, path=None, geocode=True) -> dict(counts)`; `locations.SOURCES = {'cde-public': ..., 'cde-private': ..., 'cdss-ccl': ...}` each with `url`, `parse(file) -> iterable of dicts {external_id, name, address, city, zip, lat, lng, metadata, cds_code}`; `locations.geocode_cached(address) -> (lat, lng) | None` using `django.core.cache` key `regions:geocode:<sha1 of cleaned address>` TTL 30 days.

- [ ] Write failing tests using the sample files: counts, filters (closed/virtual/adult/non-SJV/family-home/enrollment<6 skipped), county and district resolution against fixture regions (`pesticides-explorer` fixture has Fresno 9001, Kern 9002 squares — put sample coordinates inside them), idempotent re-run (updated not duplicated), removal of rows missing from the source, geocode called only for rows lacking coordinates (patch `camp.apps.regions.locations.geocode_cached`), `--no-geocode` skips them with a count.
- [ ] Implement adapters (CDE tab-delimited via `csv` with `delimiter='\t'`, latin-1 tolerant; private CSV/XLSX — support CSV, and XLSX via `openpyxl` only if already a dependency, else document CSV export; CCL CSV with a `Facility Type` column and lat/lon columns named per the source — read the header case-insensitively and accept `Latitude/Longitude` or `Facility Latitude/Facility Longitude`).
- [ ] Command: `--source`, `--path`, `--no-geocode`; downloads with `requests` to a temp file when no path; prints the counts.
- [ ] Run `docker compose run --rm test pytest camp/apps/regions -q`; green.
- [ ] Commit: `feat(regions): import_locations for CDE schools and CDSS child care`.

### Task 3: locations API

**Files:**
- Create: `camp/api/v2/pesticides/locations.py` (`LocationListBase` + cached `LocationList`, following `sections.py`'s Base/cached split and `parse_bbox`/caps)
- Modify: `camp/api/v2/pesticides/urls.py` (route `locations/` → name `location-list`)
- Test: `camp/api/v2/pesticides/tests.py` (new `LocationEndpointTests`)

**Interfaces:**
- Produces: `GET /api/2.0/pesticides/locations/?bbox=w,s,e,n&type=public_school,child_care` → GeoJSON FeatureCollection; feature `id`=sqid, geometry Point, properties `{id, name, type, type_label, address, city, district, district_id, grade_span, capacity}`. 400 on bad bbox or unknown type; bbox capped at 3x3 degrees like sections' "zoom in" cap (reuse the sections error style).

- [ ] Write failing tests: filters by bbox and type; unknown type 400; properties present; cached (`CachedEndpointMixin`).
- [ ] Implement.
- [ ] Run `docker compose run --rm test pytest camp/api/v2/pesticides -q`; green.
- [ ] Commit: `feat(pesticides): locations endpoint for schools and child care`.

### Task 4: map markers, popup, district page panel

**Files:**
- Modify: `assets/js/pesticides/section-map.js`, `assets/css/pesticides/section-map.css`, `camp/templates/pesticides/includes/section-map.html`
- Modify: `camp/apps/pesticides/views.py` (`section_map_config` gains `locations_url` and `show_locations`), `camp/apps/pesticides/places.py` (district schools panel data), `camp/templates/pesticides/place.html`, `camp/apps/pesticides/tests/test_places.py`, `camp/apps/pesticides/tests/test_views.py`

**Interfaces:**
- Consumes: Task 3 endpoint; the sections endpoint (`/api/2.0/pesticides/sections/?bbox=&year=&county=&chemical=…`) for the 3x3 pounds.
- Produces: `places.schools_nearby(region, year, all_years, county=None) -> list of {location, lbs, applications, section_sqid, section_mtrs}` sorted by lbs desc (public, private, then child care within ties? No: sort purely by lbs desc, name asc), cached with the place stats; `stats.block_totals(rows, point, year, all_years)`: the nine sections around the point = the section containing the point plus the sections whose centroid lies within 1.5 miles (2414 m) of that section's centroid, summed.

- [ ] JS: `?locations=1` toggle in Options ("Schools & child care"), synced in `syncViewParams`; `loadLocations()` by bbox on moveend (debounced like notices), zoom >= 9 only; markers on pane `pesticide-locations` (z 440) as circleMarkers radius 5, public/private schools `#5a6b7b`, child care `#7b4fb8`, white 1.5 stroke; popup in the section-popup idiom: `<h4>name</h4>`, subline `type_label · district`, headline from a fetch of the sections endpoint with the block bbox around the point (`commonParams()` + bbox) summing the nine sections' `lbs_chemical`/`applications` per the current metric → "**N lbs** applied within about a mile in 2023"; actions "Section details" (containing section from that same response) and "District page" (when district_id). Legend note when zoomed out with the toggle on: "Zoom in to see schools and child care."
- [ ] Template/CSS: checkbox in Options; marker colours documented beside NOTICE_COLOR.
- [ ] Server: `section_map_config(..., show_locations=False)` → `data-locations-url`, `data-show-locations`; school-district place pages pass `show_locations=True` and get `schools_nearby` in context, rendered as a "Schools in this district" panel (table: name (linked to district? no — plain), type, "Lbs within about a mile" (scope-aware label like the by-year table), Applications, Section link) with `Region.short_name`-style short type labels; empty state "No schools on record in this district."
- [ ] Tests: view test that a school-district page with two fixture Locations renders the panel with lbs computed from the fixture rollup (put one Location inside section 9101 and one far away with zero); map config flags; JS can't be unit-tested here — verify by hand in the browser and say so in the report.
- [ ] Run `docker compose run --rm test pytest camp/apps/pesticides camp/api/v2/pesticides -q`; green.
- [ ] Commit: `feat(pesticides): schools and child care on the map and district pages`.

### Task 5: trend chart and deltas

**Files:**
- Create: `camp/templates/pesticides/includes/trend-chart.html`
- Modify: `camp/apps/pesticides/stats.py` (`trend_deltas`, `trend_points`), `camp/apps/pesticides/templatetags/pesticides_explorer.py` (an inclusion tag `{% trend_chart by_year year hide_lbs %}` that computes the SVG geometry), `camp/templates/pesticides/detail-base.html`, `place.html`, `home.html` (valley-wide by year from `PesticideUseTotal` chemical rows: add `by_year` to `landing_stats`), `assets/sass/sjvair/pages/pesticides.sass`
- Test: `camp/apps/pesticides/tests/test_stats.py`, `test_templatetags.py`, `test_views.py`

**Interfaces:**
- Produces: `stats.trend_deltas(by_year, year, field='lbs') -> {'previous': {'year': int, 'pct': float|None} | None, 'first': {...} | None}`; by_year rows are the existing `{'year','lbs','acres','applications'}` dicts (newest first). `stats.trend_points(by_year, field, width=320, height=90, pad=6) -> list of (x, y, year, value)` oldest→newest for the polyline.
- Template tag renders: `<figure class="trend-chart">` with an inline `<svg viewBox="0 0 320 90">` polyline, small circles per point, the selected year's circle larger and filled `$link`, year labels at both ends, and `<figcaption>` with the delta sentence per spec §2 wording ("Down 12% since 2022 · down 31% since 2014"; single year → "Only one year loaded"; all years → first-year reference only).

- [ ] Write failing tests for `trend_deltas` (up/down/unchanged/None cases), `trend_points` (monotone x, y within bounds, zero handling), the tag output (contains `<svg`, the delta sentence), and a view test that chemical detail renders `trend-chart` and the landing page renders it.
- [ ] Implement; style: chart width 100%, height auto, stroke `$link`, grid-free, tabular caption; placeholder pages (`hide_lbs`) chart `applications` and say "applications".
- [ ] Run the three test files; green.
- [ ] Commit: `feat(pesticides): trend chart and year-over-year deltas`.

### Task 6: chemicals-of-concern scope, backend

**Files:**
- Modify: `camp/apps/pesticides/stats.py` (`scope_param/scope_query` gain `concern=False`; `of_concern_chemicals()` queryset helper = `Chemical.objects.filter(_of_concern_query())`; `concern_rows(rows)` = `rows.filter(chemical__in=of_concern_chemicals())`; `landing_stats(..., concern=False)` with cache key suffix and `top_chemicals_of_concern` omitted when concern), `camp/apps/pesticides/views.py` (`year_context(..., concern=False)` adds `concern` and `scope_qs`; `scope_concern(request)`; list mixin `apply_usage`/`lbs_subquery`/`related_pks` honour it; ChemicalList restricts to `of_concern_chemicals()`; ProductList to products with a concern ProductChemical; CommodityList via rollup; summary sentence adds "of concern"; ExplorerDetailMixin `get_rollup/get_uses` filtered for product/commodity pages; chemical page not of concern → context `concern_excluded=True`, unscoped; RecordsBrowser filter; NoticeList filter `chemicals__in`; MapPage/section detail/place pages pass through), `camp/apps/pesticides/places.py` (`place_context(..., concern)`), `camp/api/v2/pesticides/sections.py` (`concern=1` param on sections/townships/section detail → `concern_rows`), `camp/api/v2/pesticides/endpoints.py` (search endpoint `concern=1` narrows chemical results)
- Tests: `test_views.py`, `test_records.py`, `test_notices.py`, `test_places.py`, `test_stats.py`, `camp/api/v2/pesticides/tests.py`

**Interfaces:**
- Produces: `?concern=1` everywhere above; `scope_query(year, all_years, county, concern)`; `year_context(..., concern=)` → context keys `concern` (bool), `scope_qs`.

- [ ] Write failing tests (fixture: chemical 1 GLYPHOSATE is IARC 2A → of concern; SULFUR not): lists narrow and pounds count concern rows only; landing totals narrow; sections endpoint `concern=1` totals; records/notices narrow; scope_query carries `concern=1`; chemical page of a non-concern chemical sets `concern_excluded`.
- [ ] Implement.
- [ ] Run `docker compose run --rm test pytest camp/apps/pesticides camp/api/v2/pesticides -q`; green.
- [ ] Commit: `feat(pesticides): chemicals of concern as explorer-wide scope (backend)`.

### Task 7: chemicals-of-concern scope, UI

**Files:**
- Modify: `camp/templates/pesticides/includes/scope-picker.html` (toggle button after the county picker: `<a class="button is-small explorer-scope-toggle{% if concern %} is-set{% endif %}" href="{% qs_replace concern=... page=None %}">` with duotone `fa-triangle-exclamation` icon (orange primary like notices) and a bulma-tooltip "Prop 65, CARB toxic air contaminants, IARC 1/2A/2B"), `includes/scope-hidden.html` (hidden `concern=1`), `includes/map-toolbar.html` (nothing: hidden include covers it), `chemical-detail.html` (note when `concern_excluded`), `home.html` (hide the "of concern" leaderboard when `concern`), list templates' headings if needed, `assets/sass/sjvair/pages/pesticides.sass` (`.explorer-scope-toggle.is-set` orange border/text like the toolbar's `is-set` blue), `assets/js/pesticides/section-map.js` (`commonParams()` sends `concern` from `data-concern`; `section_map_config` gains `concern`; `entity-picker.js` `scopeParams()` sends `concern`), `camp/templates/pesticides/includes/section-map.html` (`data-concern`)
- Tests: `test_views.py` (toggle renders, `is-set`, hidden input carried, map `data-concern="1"`, leaderboard hidden)

- [ ] Write failing tests.
- [ ] Implement; rebuild styles (`docker compose run --rm web invoke styles`); verify in the browser that toggling on the map page re-shades the map and the pickers narrow.
- [ ] Run `docker compose run --rm test pytest camp/apps/pesticides -q`; green.
- [ ] Commit: `feat(pesticides): chemicals of concern toggle in the scope bar`.
