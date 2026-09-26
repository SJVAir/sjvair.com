# Section Map on the MapTiler SDK — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task.

**Goal:** The Pesticides Explorer's interactive map runs on the MapTiler SDK (MapLibre GL) with full behavioural parity to the Leaflet map, then the Leaflet map is removed from the explorer.

**Architecture:** One plain-script module (`section-map-gl.js` during development, behind `?gl=1`; renamed to `section-map.js` at the end) with the same `window.PesticidesSectionMap.init(root)`/`adopt()` lifecycle, GeoJSON sources + fill/line/circle layers below the basemap's labels, feature-state hover, SDK popups, `IControl`s for locate/reset. The DOM/data contract of `includes/section-map.html` and `views.section_map_config` is kept except for two attributes (`data-maptiler-key`, `data-style` replacing `data-tiles`).

**Tech stack:** `@maptiler/sdk` 4.1 bundled by `invoke bundle` (esbuild) into `dist/maptiler-sdk/` (done), plain ES5-style JS like the rest of `assets/js/pesticides/`, Django templates, selenium headless smoke script (dev-only).

**Spec:** `docs/superpowers/specs/2026-09-21-section-map-gl-design.md`. **Parity checklist:** `docs/superpowers/specs/2026-09-21-section-map-inventory.md` (referenced below as INV §n; it is the source of truth for every behaviour, constant, and file:line).

## Global Constraints
See the spec's "Global constraints". Plus: read INV §1–§14 for the task's areas before coding; every constant keeps its INV §13 value; keep the JS style of `section-map.js` (IIFE, `'use strict'`, prototype methods, no build step for our own code); do not edit `assets/js/admin/leaflet-maps.js` or `camp/utils/leaflet.py`; run the smoke script before reporting; commit per task with the given message; never push.

---

### Task 1: Smoke harness, map shell, lifecycle, fitting, outlines, controls
**Files:** new `scripts/pesticides_map_smoke.py` (selenium; venv instructions in its docstring; args: base URL, page path(s), `--gl`; steps: load, wait for map load event (poll `window.PesticidesSectionMap` instance's `map.loaded()`), report console errors, hover/click hooks used by later tasks, htmx year-swap via the scope bar, expanded toggle; exits non-zero on console errors or missing map); rewrite `assets/js/pesticides/section-map-gl.js` from the spike into the real module skeleton; `camp/apps/pesticides/views.py` `section_map_config` (+ callers) adds `maptiler_key` and `style` (id, default `dataviz`) — keep `tile_url` for now (Leaflet still uses it); `camp/templates/pesticides/includes/section-map.html` adds `data-maptiler-key`, `data-style`; `assets/css/pesticides/section-map.css` additions for GL controls/popups (scoped so Leaflet CSS is untouched); tests in `camp/apps/pesticides/tests/test_views.py` for the new attributes.
**Interfaces produced:** `window.PesticidesSectionMapGL = { init }` (renamed in Task 5), `SectionMap` with `init()`, `adopt(newEl)` (INV §12.4 semantics incl. `DATA_KEYS`, `attachControls()` rebinding, `map.resize()`), `commonParams()`, `setStatus()`, `fitCounty()`, `resetView()`, `loadCounties()`, `loadOutline()`, `drawRadius()`, `locate()`/`showLocation()`, `toggleExpanded()`/`setExpanded()`/`fitBelowNavbar()`, panel toggles, scroll-zoom rules, `?tiles=` → SDK style id, reduced-motion flag, WebGL check. Layers: `counties-line`, `outline-line`, `radius-*`, all inserted before the first symbol layer (helper `beforeLabels()`).
- [ ] Read INV §1, §2 (tiles only), §9, §10, §11, §12, §13, §14, §16 and the spike.
- [ ] Failing Python tests for `data-maptiler-key`/`data-style`; implement config + template.
- [ ] Implement the module shell: creation options per spec §3, controls (SDK navigation top-left; Locate + Reset as `IControl`s with the same markup/aria as INV §9), expand/options/panels wiring unchanged from Leaflet (copy the DOM code), fitting per INV §10 (counties GeoJSON bounds for the valley fit, `fitCounty`, outline, center/zoom, radius circle as a 64-point polygon), status/aria-live, abortable requests helper, lifecycle per INV §12 (in-place adopt; expanded clear when the map disappears).
- [ ] Smoke script passes on: landing (`/tools/pesticides/?gl=1`), Fresno county, Tulare city, a section page, a district page; an htmx year change keeps the same map instance (assert `instances()[0]` identity unchanged, no new `mtsid`); expand/collapse works.
- [ ] Commit `feat(pesticides): GL section map shell — lifecycle, fitting, outlines, controls`.

### Task 2: Grid, classing, legend, popups, URL sync, All sections
**Files:** `section-map-gl.js`; `camp/apps/pesticides/views.py` (`SectionDetailBase.top()` adds `is_of_concern`, spec §3b) + `camp/apps/pesticides/tests/test_sections.py`; `camp/api/v2/pesticides/locations.py` docstring fix; `section-map.css` (GL popup classes mirroring `.section-popup*`).
**Interfaces produced:** `loadGrid()`/`loadTownships()`/`loadSections()` with INV §4 (`sectionZoom()`, `MAX_VIEWPORT_SECTIONS`, `covers()`, `geometry=0` values-only refetch + township geometry cache, `BBOX_PAD`, `DEBOUNCE_MS`, abort, 400→unpadded→township fallback chain), classing per INV §6 (writes `fill`/`opacity` properties; legend DOM; ramps/bins/tiles selectors), styling per INV §3 as paint expressions (level widths, zoom-stepped lines for `SECTION_LINES_MIN_ZOOM`, no-data invisibility below threshold, hover via feature-state, selected outline layer, highlight layer), popups per INV §7.1–7.3 (township, section incl. top chemicals/products fetch and links, selected persistence, `reopenSelectedSection`/`reopenGridPopup`, popup buttons), URL sync per INV §2 for `metric`/`ramp`/`bins`/`tiles`/`sections`, All-sections mode per INV §5.6 on an `all-sections` source (5×5 block fetches, scheduled draw with cancel, classing over visible, legend change, grid fill hidden while active).
- [ ] Read INV §2–§7 (7.4/7.5 excluded), §13.
- [ ] Failing test for `is_of_concern` in section top chemicals; implement.
- [ ] Implement; smoke script extended: township popup opens on click, "Zoom in" reaches section level, section popup shows top chemicals, selected outline survives a metric change, `?sections=1` draws >1,000 features at the county zoom, legend rows match class count.
- [ ] Commit `feat(pesticides): GL section map grid — classes, legend, popups, all sections`.

### Task 3: The lens
**Files:** `section-map-gl.js`.
**Interfaces produced:** `showLens`/`drawLens`/`clearLens`/`cancelLensFetch`/`fetchLensSections`/`prefetchRing`/`neighborhoodOf` per INV §5.1–5.5: 50 ms rest, reach 1.5 neighbourhood over the loaded township features' bounds (precomputed bboxes), **per-township cache keyed by township id (mtrs prefix), exactly as production** (INV §5.2; not the spike's joined key), prefetch ring, classing over the block, lens outline from the real host geometries (union outline = the hosts' polygons rendered as a line layer, not a bbox), clear delays, `openLensId` pinning while a lens-section popup is open, lens-section popups (INV §7.3 variant), hover styles on lens sections.
- [ ] Read INV §5, §7.3, §13.
- [ ] Implement; smoke script: hover a township at zoom 9 → lens source has >0 features within 1.5 s; moving one township over reuses cached neighbours (assert ≤1 new sections request); popup on a lens section pins the lens.
- [ ] Commit `feat(pesticides): GL section map lens`.

### Task 4: Notices and locations layers
**Files:** `section-map-gl.js`; `section-map.css` if needed.
**Interfaces produced:** `loadNotices`/`renderNotices`/`clearNotices`, `loadLocations`/`renderLocations`/`clearLocations`/`loadLocationBlock` per INV §8 and popups per INV §7.4–7.5 (notice popup in the section-popup idiom; location popup with the 3×3 block totals and the "District page" pill), circle layers with the INV §13 colours/sizes/rings, `?notices=`/`?locations=` sync and defaults (`data-show-*`), the bbox cap + unpadded fallback, legend marker rows, adopt() interactions (INV §12.4: default changes, reload on data change).
- [ ] Read INV §7.4–7.5, §8, §12.4, §13.
- [ ] Implement; smoke script: on a district page `?locations=1` renders markers, clicking one opens a popup with a District page pill; on a county page notices render and a notice popup opens; toggling via Options updates the URL.
- [ ] Commit `feat(pesticides): GL section map notices and locations`.

### Task 5: Flip to GL, remove Leaflet from the explorer
**Files:** `git mv assets/js/pesticides/section-map-gl.js assets/js/pesticides/section-map.js` (delete the Leaflet module), `camp/templates/pesticides/base.html` (load `maptiler-sdk/maptiler-sdk.css` + `.js` always; remove the `?gl` block; keep `js/admin/leaflet/leaflet.js` + `leaflet-maps.js` + their CSS for the county choropleths), `includes/section-map.html` (drop `data-gl` and `data-tiles`), `views.py` (drop `tile_url` from `section_map_config` only if nothing else reads it — the admin helper keeps its own), `explorer.js` (single `PesticidesSectionMap.init` call, GL ordering removed), `section-map.css` (delete Leaflet-only rules, keep GL ones; the county-choropleth CSS lives in `admin/leaflet-maps.css` and is untouched), tests, `docs/` (spec/inventory stay as history), memory note, PR deploy notes (`invoke bundle` is part of `invoke build`; hard refresh).
- [ ] Rename and flip; grep for `data-gl`, `PesticidesSectionMapGL`, `__glStats`, `tileUrlFor`, `L.` in the explorer JS — none remain.
- [ ] Full suite green; smoke script (no `--gl`) passes on all five pages incl. htmx swaps and expanded mode; headless screenshots of landing, county, section, district saved to the report.
- [ ] Commit `feat(pesticides): the section map runs on the MapTiler SDK; Leaflet leaves the explorer`.
