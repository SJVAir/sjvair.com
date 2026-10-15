# Pesticides Township Grid and County Outlines Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Every section map shows the county outlines, and at the default (valley-wide) zoom it shows a shaded township grid instead of a "zoom in" message; square-mile sections take over when zoomed in.

**Architecture:** Two small GeoJSON endpoints next to the existing sections API: `counties/` (the eight county boundaries, simplified, cached a day) and `townships/` (one feature per PLSS township — the `MDM-T14S-R20E` prefix of an MTRS name — with the envelope of its sections as geometry and rollup totals for the year and filters). The map script draws counties as a non-interactive outline pane on every map, and swaps between the township layer (zoom < 11) and the section layer (zoom ≥ 11) using the same quantile shading, legend, metric toggle, and popup pattern. Notices load at every zoom (the endpoint already caps at 2,000).

**Tech Stack:** Django 5.2 + PostGIS, django-resticus v2 (`CachedEndpointMixin` — keep the `*Base` + cached subclass split), plain Leaflet 1.9 + ES2017 JS.

**Spec:** `docs/superpowers/specs/2026-09-16-pesticides-explorer-v2-design.md`, section "2. Interactive section map" (this plan amends it: townships at low zoom, county outlines always).

## Global Constraints

- Commands from the worktree root inside Docker: `docker compose run --rm test pytest camp/api/v2/pesticides camp/apps/pesticides -q`; `node --check assets/js/pesticides/section-map.js`. `dist/css/style.css` is git-ignored.
- Tests: `django.test.TestCase`, fixtures (`pesticides-explorer`: counties 9001 Fresno / 9002 Kern with square boundaries; MTRS 9101 `MDM-T14S-R20E-01` in Fresno, 9102 `MDM-T30S-R28E-01` in Kern; rollup rows via `RollupTestMixin`), plain `assert`. API tests live in `camp/api/v2/pesticides/tests.py`.
- Explorer pages never link to raw API endpoints (the JS may fetch them). No AI attribution in commits (no co-author trailers). Never `git add -A`.
- A dev server for this worktree runs on port 8002; do not start/stop servers.

---

## File map

| File | Responsibility |
|---|---|
| `camp/api/v2/pesticides/sections.py` | + `CountyList` (GeoJSON of county boundaries), `TownshipListBase`/`TownshipList` (GeoJSON of townships with totals); section coordinates rounded to 5 decimals |
| `camp/apps/pesticides/stats.py` | + `by_township(rows, year, lbs_field)` → totals keyed by township name |
| `camp/apps/pesticides/townships.py` | township key helpers: `township_of(mtrs_name)`, `township_geometries()` (cached envelopes), `township_section_counts()` |
| `camp/api/v2/pesticides/urls.py` | + `counties/`, `townships/` |
| `camp/apps/pesticides/views.py` | `section_map_config` adds `counties_url`, `townships_url` |
| `camp/templates/pesticides/includes/section-map.html` | + `data-counties-url`, `data-townships-url`; status/legend copy |
| `assets/js/pesticides/section-map.js`, `assets/css/pesticides/section-map.css` | county pane, township layer, zoom switch |
| `camp/api/v2/pesticides/tests.py`, `camp/apps/pesticides/tests/test_stats.py` | tests |

---

### Task 1: Township totals, township geometries, and the two GeoJSON endpoints

**Files:** create `camp/apps/pesticides/townships.py`; modify `stats.py`, `camp/api/v2/pesticides/sections.py`, `urls.py`, `views.py` (`section_map_config`), tests.

**Interfaces (produces):**

```python
# camp/apps/pesticides/townships.py
TOWNSHIP_GEOMETRIES_KEY = 'pesticides:township-geometries'   # 1 day
TOWNSHIP_SECTIONS_KEY = 'pesticides:township-sections'       # 1 day

def township_of(mtrs_name: str) -> str        # 'MDM-T14S-R20E-01' → 'MDM-T14S-R20E' (drop the last '-NN'); returns the name unchanged if it has no '-NN' suffix
def township_index() -> dict[int, str]        # {mtrs_pk: township}, from Region.objects.filter(type=MTRS).values_list('pk', 'name'); cached a day under TOWNSHIP_SECTIONS_KEY
def township_geometries() -> dict[str, dict]  # {township: {'geometry': <GeoJSON dict of ST_Envelope(ST_Collect(boundary geometries))>, 'sections': <count>, 'bbox': (west, south, east, north)}}; one GROUP BY query using Django ORM annotate with Envelope(Collect('boundary__geometry')) on Region MTRS grouped by an annotated Substr/Left of name (or a raw query — either is fine; keep it to one query); coordinates rounded to 5 decimals; cached a day under TOWNSHIP_GEOMETRIES_KEY
```

```python
# camp/apps/pesticides/stats.py
def by_township(rows, year, lbs_field='lbs_chemical') -> dict[str, dict]
    # {township: {'lbs_chemical', 'lbs_product', 'acres_treated', 'applications'}} built by summing by_section-style rows (rows.filter(year=year, mtrs__isnull=False).values('mtrs').annotate(...)) through township_index(); no per-township queries
```

API (`camp/api/v2/pesticides/sections.py`, mirroring `SectionList`'s structure and error handling):

- `GET /api/2.0/pesticides/counties/` (`CountyList`, `CachedEndpointMixin`, TTL 1 day): FeatureCollection of the eight county boundaries from `maps.county_geometries()` (already simplified and cached) — features `{type, id: <sqid>, geometry, properties: {id, name, slug}}`. Name lookup via one `Region.objects.in_bulk`.
- `GET /api/2.0/pesticides/townships/?year=&bbox=&chemical=&product=&commodity=&county=` (`TownshipListBase` + `TownshipList` cached 1 h): resolves `year` and the entity/county filters exactly like `SectionList` (reuse its helpers — lift them to module functions if they are methods), builds `rows` = rollup filtered by those, computes `by_township(rows, year)`, then returns one feature per township in `township_geometries()` whose bbox intersects the requested `bbox` (or all when absent), with properties `{id: township, name: township, sections, lbs_chemical, lbs_product, acres_treated, applications}` (zeros when no rows). No count cap (≤ 878). Invalid bbox → 400 like `SectionList`.
- `SectionList`: round emitted coordinates to 5 decimals (a small `round_coords(geojson_dict)` helper applied to the geometry dict) — this roughly halves the payload.
- `section_map_config` adds `'counties_url': '/api/2.0/pesticides/counties/'` and `'townships_url': '/api/2.0/pesticides/townships/'`; the include emits `data-counties-url` / `data-townships-url`.
- OpenAPI: check `camp/api/v2/tests/test_openapi.py` still passes; add docstrings on the two new cached classes in the same style as `ActiveNoticeList`.

- [ ] **Step 1: Tests (RED)** — in `camp/api/v2/pesticides/tests.py` add a `TownshipAndCountyTests(RollupTestMixin, TestCase)` class (import the mixin from `camp.apps.pesticides.tests.rollup_mixin`):

```python
def test_township_of(self):
    from camp.apps.pesticides.townships import township_of
    assert township_of('MDM-T14S-R20E-01') == 'MDM-T14S-R20E'
    assert township_of('MDM-T14S-R20E') == 'MDM-T14S-R20E'

def test_counties_geojson(self):
    response = self.client.get('/api/2.0/pesticides/counties/')
    assert response.status_code == 200
    data = response.json()
    assert data['type'] == 'FeatureCollection'
    names = sorted(f['properties']['name'] for f in data['features'])
    assert names == ['Fresno County', 'Kern County']
    assert data['features'][0]['geometry']['type'] in ('Polygon', 'MultiPolygon')

def test_townships_geojson_totals(self):
    response = self.client.get('/api/2.0/pesticides/townships/', {'year': 2023})
    assert response.status_code == 200
    features = {f['properties']['id']: f['properties'] for f in response.json()['features']}
    assert features['MDM-T14S-R20E']['lbs_chemical'] == 670.0
    assert features['MDM-T14S-R20E']['applications'] == 4
    assert features['MDM-T14S-R20E']['sections'] == 1
    assert features['MDM-T30S-R28E']['lbs_chemical'] == 70.0

def test_townships_bbox_and_filters(self):
    kern_only = self.client.get('/api/2.0/pesticides/townships/', {'year': 2023, 'bbox': '-119.1,35.3,-119.0,35.4'}).json()
    assert [f['properties']['id'] for f in kern_only['features']] == ['MDM-T30S-R28E']
    chem = self.client.get('/api/2.0/pesticides/townships/', {'year': 2023, 'chemical': 253}).json()
    by_id = {f['properties']['id']: f['properties'] for f in chem['features']}
    assert by_id['MDM-T14S-R20E']['lbs_chemical'] == 20.0
    assert self.client.get('/api/2.0/pesticides/townships/', {'bbox': 'nope'}).status_code == 400

def test_section_coordinates_rounded(self):
    response = self.client.get('/api/2.0/pesticides/sections/', {'year': 2023, 'bbox': '-119.9,36.6,-119.7,36.8'})
    ring = response.json()['features'][0]['geometry']['coordinates'][0][0]
    assert all(len(str(abs(v)).split('.')[-1]) <= 5 for pair in ring for v in pair)
```

  (Fixture check: 2023 Fresno section 9101 = uses 1,2,4,6 = 670 lbs / 4 applications; chlorpyrifos (chem_code 253) in 9101 = use 4 = 20 lbs; Kern section 9102 = uses 3,5 = 70 lbs. Verify against `fixtures/pesticides-explorer.yaml` and correct the test, not the code, if a value is off.) Also add a `by_township` unit test in `camp/apps/pesticides/tests/test_stats.py`.
- [ ] **Step 2: Run** → fails (no module / 404).
- [ ] **Step 3: Implement** as specified. Keep `township_geometries()` to one query; a raw SQL `GROUP BY left(name, length(name) - 3)` with `ST_AsGeoJSON(ST_Envelope(ST_Collect(geometry)), 5)` is acceptable.
- [ ] **Step 4: GREEN** on `camp/api/v2/pesticides camp/apps/pesticides camp/api/v2/tests/test_openapi.py`.
- [ ] **Step 5: Commit** — `feat(api): add county outlines and township grid GeoJSON for the pesticides map`.

---

### Task 2: County outlines and the township layer in the map script

**Files:** `assets/js/pesticides/section-map.js`, `assets/css/pesticides/section-map.css`, `camp/templates/pesticides/includes/section-map.html`, `camp/templates/pesticides/map.html` (copy), `camp/apps/pesticides/tests/test_views.py` (map page includes the new data attributes).

**Behavior contract (plain ES2017, no build step):**

1. `SECTION_ZOOM = 11` replaces `MIN_SECTION_ZOOM = 9`. At `zoom >= SECTION_ZOOM` the section layer loads exactly as today; at lower zooms the township layer loads instead (`townships_url` with the same `year`/entity/county params and the viewport `bbox`), debounced and abortable the same way, and the section layer is removed. Never show a "zoom in" status for townships; if the township request fails, show `Couldn't load the grid; try again`.
2. Township features are styled with the same `quantileClasses` over the township values in view, the same metric toggle (`lbs_chemical` / `applications`), and the same legend, whose unit label becomes `lbs per township` / `applications per township` while the township layer is active (a `<span class="section-map-level">` under the legend says `Each square is a 6 × 6 mile township; zoom in for square-mile sections.` vs `Each square is one square-mile section.`).
3. Township popup: name, `N sections`, the metric value, and a link-styled button `Zoom in` that calls `map.setView(center of the feature, SECTION_ZOOM)`. No detail fetch.
4. County outlines: on init, fetch `counties_url` once and add a `L.geoJSON` layer in a dedicated pane `pesticide-counties` (`zIndex 420`, above the overlay pane's fills, below the notices pane at 450), style `{ color: '#1f2d3d', weight: 1.5, fill: false, opacity: 0.8, interactive: false }`. Dashed (`dashArray: '4 3'`) at zoom ≥ SECTION_ZOOM so it does not compete with the section grid. Failure is silent (console.error).
5. `loadNotices()` no longer gates on zoom; a 400 from the notices endpoint clears the layer and logs, nothing else.
6. Section-map status area: the "Zoom in to see square-mile sections" message is gone (the grid is always there). Keep error messages.
7. The map page copy (`map.html`) and the include's footer sentence describe the two levels in one sentence each.

- [ ] **Step 1:** update `test_views.py`'s map-page test to assert `data-counties-url` and `data-townships-url` are rendered (RED), then implement the include/config change (GREEN).
- [ ] **Step 2:** implement the script and CSS; `node --check`. Manually verify in a browser at http://localhost:8002/tools/pesticides/map/ (default zoom shows the shaded township grid with county outlines; zoom 11+ shows sections with dashed county outlines; notices at both), the records page, and a notices page.
- [ ] **Step 3: Commit** — `feat(pesticides): show county outlines and a township grid at low zoom on the section maps`.

---

### Task 3: Browser check and wrap-up (controller)

Chrome on port 8002: `/map/` at default zoom (grid + outlines + notices), zoom in through 10 → 11 (switch), metric toggle at both levels, township popup "Zoom in", `/records/?county=fresno`, `/notices/`, a place page. Timings for `townships/` cold and warm. One fix dispatch if needed. Ledger. No push.
