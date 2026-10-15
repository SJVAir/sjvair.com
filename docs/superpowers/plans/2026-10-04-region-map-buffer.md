# Region Map Buffer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** On a region's pesticides tabs, `?buffer=0|1|3|5` clips every map layer to the region's boundary widened by that many miles, frames the map on it, and draws the widened edge dashed; a toolbar dropdown picks it.

**Architecture:** Shared shape helpers in `camp/apps/regions/shapes.py` (both explorers). The pesticides map APIs accept `region=<sqid>&buffer=N` (the names emissions uses) and filter to `region_shape(region, N)`. Region area tabs put the clip into `map_config`; the section map adds it to every layer fetch, fits the widened shape and draws it dashed.

**Tech Stack:** Django/GeoDjango (GEOS), django-resticus endpoints, MapLibre section map, Bulma.

**Spec:** `docs/superpowers/specs/2026-10-04-region-map-buffer-design.md`

## Global Constraints

- Worktree `/home/derek/dev/ccac/sjvair.com/.claude/worktrees/feature+pesticides-explorer`, branch `feature/pesticides-explorer`; absolute paths, `git -C <worktree>`; never the main checkout.
- Tests: `django.test.TestCase`, plain `assert`. Run `docker compose run --rm test pytest <paths> -n 4 --dist loadscope -q` from the worktree.
- Commit locally per task, explicit file lists, no AI attribution, never push.
- `BUFFERS = (0, 1, 3, 5)`; labels "Exact boundary", "+1 mile", "+3 miles", "+5 miles"; widen in EPSG 3310 by `miles * 1609.344` m, `simplify(30, preserve_topology=True)`, back to 4326; cache a day per region sqid + miles as hex EWKB; miles=0 → the boundary itself, uncached.
- API clip params are `region=<sqid>` + `buffer=<miles>` (shared naming with emissions). `camp/apps/regions` must not import from `camp.apps.pesticides`.
- Dashed edge: the region outline's colour, 1.5 px, `line-dasharray` [3, 3].
- Only region area tabs (Overview, Notices, Records, Schools) get the clip and control; near-me tabs, the main map and entity/section pages don't. Stats and tables are unchanged.
- Static after JS/Sass changes: `docker exec sjvair-web-run-9fa08fbbbf15 sh -c 'invoke styles && python manage.py collectstatic --noinput -v0'`.

## Review Focus

1. A county tab: today its map narrows by `county=` (no outline); with the clip it must still frame and show only the county (+ buffer) — not the whole valley, not a blank map (Task 3/4 smoke).
2. Switching tabs and changing filters keeps `buffer` (tab links, scope bar, filter forms' hidden inputs) — Task 3 tests.
3. Bad `region`/`buffer` on any endpoint → 400, never 500; an endpoint called without them behaves exactly as before (Task 2 tests).
4. The township grid at county/valley zoom paints nothing outside the shape (Task 2 test + Task 4 smoke).
5. The +5 mi shape of a large county can exceed the sections cap at low zoom — the map's existing "zoom in" handling applies, not an error page (Task 4 smoke).

---

### Task 1: Shared shape helpers (standalone commit for emissions)

**Files:** Modify `camp/apps/regions/shapes.py` (existing module — add, don't restructure); Test `camp/apps/regions/tests/test_shapes.py` (create, or extend if it exists).

**Interfaces — Produces:**
- `BUFFERS = (0, 1, 3, 5)`; `BUFFER_LABELS = {0: 'Exact boundary', 1: '+1 mile', 3: '+3 miles', 5: '+5 miles'}`
- `buffer_param(params) -> int` — int in BUFFERS from `params.get('buffer')`, else 0 (junk, negatives, other ints → 0).
- `region_shape(region, miles=0) -> GEOSGeometry` (srid 4326) — boundary at 0 (transformed to 4326 if stored otherwise); widened + simplified + cached otherwise (key e.g. `f'regions:shape:v1:{region.sqid}:{miles}'`, TTL 86400, value `geometry.hexewkb`, rebuilt with `GEOSGeometry`). Region without a boundary → `None`.
- `buffer_options(request, current) -> [{'label', 'url', 'current'}]` — the request's path + GET with `buffer` set (omitted for 0) and `page` removed.

- [ ] **Step 1: Failing tests** — buffer_param cases; region_shape(…, 0) equals the boundary; (…, 1) contains the boundary, its area is larger, a point ~0.9 mi outside the boundary is inside and ~1.1 mi outside is not (build a small square Region boundary in setUp; offsets via 3310); second call is served from cache (assert `cache.get(key)` set, or patch the builder); buffer_options for `?year=2022&page=3&buffer=1` → four entries, the +1 current, URLs keep `year`, drop `page`, buffer=0 URL has no `buffer`.
- [ ] **Step 2: Run, expect FAIL.** **Step 3: Implement** (imports `EPSG_CALIFORNIA_ALBERS`, `EPSG_LATLON` from `camp.utils.gis`). **Step 4: Run** `camp/apps/regions` — pass.
- [ ] **Step 5: Commit** — `feat(regions): region shapes widened by a buffer, shared by both explorers`

---

### Task 2: Map APIs take a region + buffer clip

**Files:** Modify `camp/api/v2/pesticides/sections.py` (SectionList.get_sections ~241, TownshipList.get ~482-559, ActiveNoticeListBase.get ~423), `camp/api/v2/pesticides/locations.py` (`parse_area` ~128); Test `camp/api/v2/pesticides/tests.py`.

**Interfaces — Consumes:** Task 1 `region_shape`, `buffer_param`, `BUFFERS`. **Produces:** a helper `clip_shape(params) -> (geometry | None, error | None)` in sections.py (or a small module beside it) — no `region` param → `(None, None)`; `region` → `Region(sqid=…, boundary__isnull=False)` else error `'region not found'`; `buffer` present but not in BUFFERS → error `'buffer must be one of 0, 1, 3, 5'`; else `(region_shape(region, buffer), None)`. Cache it per request (it may be called once per endpoint call only).

Per endpoint (the clip combines with every existing filter; absent → unchanged behaviour):
- **Sections:** `sections.filter(boundary__geometry__intersects=shape)` — applied with bbox, or alone (a clip with no bbox and no lat/lng is a valid request now: replace the "give bbox…" error when a clip is given). Keep the MAX_SECTIONS cap.
- **Townships:** cached `township_geometries()` entries — keep only those whose geometry intersects the shape (bbox prefilter via the cached bbox, then `GEOSGeometry`/geometry `.intersects`). Check what type the cached geometry is and intersect accordingly.
- **Notices (active and archive — one base):** `notices.filter(point__within=shape)` (point may be null → excluded when clipped).
- **Locations:** `parse_area`: `region=` keeps meaning "within the region" and now honours `buffer` → `{'point__within': region_shape(region, buffer)}`; a bad buffer → 400.

- [ ] **Step 1: Failing tests** — for each endpoint, a fixture with features inside the region, inside the +1 buffer only, and outside: `region=` alone returns inside only; `region=&buffer=1` adds the buffer ones; combined with a bbox it's the intersection; `region=nope` and `buffer=2` → 400; no clip → unchanged result (compare with the existing tests' expectations). Use the `pesticides-explorer` fixture's MTRS sections/regions where possible; build Regions with boundaries in setUp where needed.
- [ ] **Step 2: FAIL. Step 3: Implement. Step 4: Run** `camp/api/v2/pesticides camp/apps/pesticides` — pass.
- [ ] **Step 5: Commit** — `feat(api): the pesticides map layers clip to a region and buffer`

---

### Task 3: Region tabs put the clip in the map config; buffer survives navigation; toolbar control

**Files:** Modify `camp/apps/pesticides/views.py` (`section_map_config` ~1172; `AreaPageMixin` ~2260 `scope_query`/`tabs`/`header_context`; `AreaNoticesMixin.get_map_config` ~2526; `AreaRecordsMixin` — RecordsBrowser's map config when an area is present; `AreaSchoolsMixin` ~2615), `camp/apps/pesticides/places.py` (`place_context` ~690 — Overview map; its cache key must include the buffer), `camp/templates/pesticides/includes/scope-hidden.html`, a new toolbar include for the dropdown (follow the Compare dropdown pattern in `pesticides/includes/map-toolbar.html` ~48-70: `div.dropdown.map-toolbar-dropdown` with `<a class="dropdown-item">` links), `camp/templates/maps/includes/map.html` only if the toolbar can't take an extra include otherwise; also a regions API addition for the widened outline (below). Test: `camp/apps/pesticides/tests/test_places.py` (or a new `test_buffer.py`).

**Interfaces — Consumes:** Task 1 helpers; Task 2's `region=&buffer=` API params. **Produces (map_config / data keys the JS reads):**
- `clip_region` (region sqid) and `buffer` (int) — present on region tabs only.
- `clip_url` — GeoJSON of the widened shape, e.g. `/api/2.0/regions/<sqid>/?buffer=N` (add `buffer` support to the regions detail endpoint the outline already uses: when `buffer` > 0 the response's boundary geometry is `region_shape(region, buffer)` — or a sibling endpoint; check the regions API and pick the smaller change; emissions may use it too).
- `buffer_options` in context for the toolbar dropdown (from `buffer_options(request, buffer)`), shown only when `clip_region` is set; the map gets a toolbar on these tabs (`toolbar=True` already exists — make the area-tab toolbar render only the buffer dropdown, not MapPage's filter dropdowns).
- Every region area tab — including **county** tabs (which today narrow by `county=` with no outline) and the **Records** tab (whose map today has no outline) — passes the clip; county tabs keep `county=` for the numbers.
- `buffer` is carried: `AreaPageMixin.scope_query()` appends `buffer=N` when non-zero (so tab links and the crumb carry it); `scope-hidden.html` adds a hidden `buffer` input when the request has one (filter forms); `section_map_config`'s `scope_suffix` / section popup links don't need it (section pages aren't clipped). Near-me tabs never emit it.

- [ ] **Step 1: Failing tests** — for a city region and a county region tab (Overview, Notices, Records, Schools) with `?buffer=3`: `map_config` has `clip_region`, `buffer == 3`, `clip_url` with `buffer=3`; the four `buffer_options` with +3 current; tab URLs and the Overview crumb carry `buffer=3`; a filter form has `<input type="hidden" name="buffer" value="3">`; with no buffer: `buffer == 0`, tab URLs have no `buffer`; near-me tabs: no `clip_region`, no options. The regions endpoint with `buffer=3` returns a geometry larger than without. Overview's cached map config differs per buffer.
- [ ] **Step 2: FAIL. Step 3: Implement. Step 4: Run** `camp/apps/pesticides camp/apps/regions camp/api` — pass.
- [ ] **Step 5: Commit** — `feat(pesticides): region tabs clip their map to a buffer the toolbar picks`

---

### Task 4: The section map clips, frames and draws the buffer

**Files:** Modify `assets/js/pesticides/section-map.js`; Sass for the dropdown if needed; `scripts/pesticides_map_smoke.py` (a buffer check).

**Interfaces — Consumes:** Task 3 data keys `clipRegion`, `buffer`, `clipUrl` (camelCased by `dataset`).

- `commonParams()` (~1597) adds `region: data.clipRegion, buffer: data.buffer` when `clipRegion` is set (sections, townships, lens, location block all use it). The notices params (~3166) and both locations modes (~3521 area mode — add `buffer` to `areaParams`; ~3563 bbox mode — add region+buffer) add them too. Check `loadLocationBlock`'s stale-scope key still works.
- Outline: keep the region outline (`outlineUrl`) as is; add a `buffer-line` layer (source `buffer-outline`) from `clipUrl`, line colour = `OUTLINE_COLOR`, width 1.5, `line-dasharray` [3, 3], above `outline-line`; nothing at buffer 0 (still fetch nothing). Frame: fit to the `clipUrl` shape's bounds (padding as `loadOutline`), and `home()` prefers it.
- The outline mask (`outline-mask`, which dims outside the region) should dim outside the **buffer** shape when a buffer is set, so the clipped-in ring isn't dimmed.
- On htmx adopt (`onAdopt`, ~1296-1340), a change to `clipRegion`/`buffer`/`clipUrl` clears loaded grid/notices/locations bounds and reloads them and the buffer outline (follow how `outlineUrl` and `county` changes are handled).
- County tabs: with the clip present, `pendingFit` / `fit` must frame the clip shape, not the valley (check `fitCounty` and `settleFit`).
- Smoke: add `check_buffer` — on a page with `clipRegion`, no rendered section/notice/location lies outside the clip shape's bounds+tolerance; the `buffer-line` layer renders iff buffer > 0; the fit's bounds contain the shape. Run on a county Overview tab and a city Overview tab at `buffer=0` and `buffer=3`, and on `/tools/pesticides/map/` (unchanged).

- [ ] Steps: implement; rebuild static; run the four smoke URLs + the main map; run the test suites; commit — `feat(pesticides): the section map clips to the region's buffer and draws its edge`.
