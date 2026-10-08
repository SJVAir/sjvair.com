# Pesticides Explorer — Section Map Behavioural Inventory (Leaflet → MapTiler SDK/MapLibre GL port)

Source of truth: `feature/pesticides-explorer` branch, worktree
`.claude/worktrees/feature+pesticides-explorer`. This is a parity checklist for
porting `assets/js/pesticides/section-map.js` (Leaflet) to the MapTiler SDK
spike `assets/js/pesticides/section-map-gl.js` (MapLibre GL). All references
are `file:line` against that worktree as of 2026-09-21.

## 1. DOM contract

### 1.1 `data-*` attributes on `.section-map`

Rendered by `camp/templates/pesticides/includes/section-map.html:2-30` from `map_config` (built by `section_map_config`, `camp/apps/pesticides/views.py:1010`). Read in `assets/js/pesticides/section-map.js`:

| attribute | html source line | js read site(s) | meaning |
|---|---|---|---|
| `data-sections-url` | section-map.html:3 | `this.data.sectionsUrl` — js:1326, 1569, 1631, 1737, 2678 | GeoJSON sections endpoint |
| `data-counties-url` | section-map.html:4 | `this.data.countiesUrl` — js:1017 | county outlines GeoJSON (fetched once) |
| `data-townships-url` | section-map.html:5 | `this.data.townshipsUrl` — js:1382 | GeoJSON townships endpoint |
| `data-notices-url` | section-map.html:6 | `this.data.noticesUrl` — js:2376 | notices GeoJSON endpoint |
| `data-locations-url` | section-map.html:7 | `this.data.locationsUrl` — js:2509 | schools/child-care GeoJSON endpoint |
| `data-section-url-pattern` | section-map.html:8 | `this.data.sectionUrlPattern` — js:2347 | per-section detail JSON (top chemicals), `{id}` templated |
| `data-section-page-url` | section-map.html:9 | `this.data.sectionPageUrl` via `sectionUrl()` js:1114 | section detail page link, `{id}` templated |
| `data-chemical-page-url` | section-map.html:10 | `this.data.chemicalPageUrl` via `chemicalUrl()` js:1110 | chemical page link |
| `data-product-page-url` | section-map.html:11 | `this.data.productPageUrl` via `productUrl()` js:1118 | product page link |
| `data-notice-page-url` | section-map.html:12 | `this.data.noticePageUrl` via `noticeUrl()` js:1122 | notice detail page link |
| `data-tiles` | section-map.html:13 | `this.data.tiles` — js:695,716-717,1138 | base MapTiler tile URL template (style baked in) |
| `data-attribution` | section-map.html:14 | `this.data.attribution` — js:720 | tile attribution HTML |
| `data-year` | section-map.html:15 | `this.data.year` — js:2190(`yearPhrase`),2349,2357,commonParams | active year, or `"all"` |
| `data-year-label` | section-map.html:16 | `this.data.yearLabel` — js:2189 | human label for `yearPhrase()` |
| `data-chemical` | section-map.html:17 | `commonParams()` js:1214 | chemical filter id |
| `data-product` | section-map.html:18 | `commonParams()` js:1215 | product filter id |
| `data-commodity` | section-map.html:19 | `commonParams()` js:1216 | commodity filter id |
| `data-county` | section-map.html:20 | `commonParams()` js:1217, `fitCounty()` js:1042, `resetView()` js:829, `loadLocations()` js:2535 | county filter slug |
| `data-concern` | section-map.html:21 | `commonParams()` js:1218 | chemicals-of-concern filter flag |
| `data-highlight` | section-map.html:22 | `this.data.highlight` — js:1459 (`isHighlighted`) | id of the page's "own" section to outline in orange |
| `data-outline-url` | section-map.html:23 | `this.data.outlineUrl` — js:1065 | region boundary endpoint (city/ZIP/place pages) |
| `data-center` | section-map.html:24 | `parseCenter(this.data.center)` — js:699,840,971,1100 | initial `"lat,lng"` |
| `data-zoom` | section-map.html:25 | `parseInt(this.data.zoom,10)` — js:700,840,975 | initial zoom |
| `data-radius` | section-map.html:26 | `this.data.radius` — js:900 (`drawRadius`) | miles radius circle to draw/fit around center |
| `data-fit` | section-map.html:27 | `this.data.fit` — js:1049 (`fitCounty`) | `"valley"` triggers valley-wide fit/refit behaviour |
| `data-show-notices` | section-map.html:28 | `this.data.showNotices` — js:346,1172,932,489 | page default for the notices toggle (`'0'` = off; anything else = on) |
| `data-show-locations` | section-map.html:29 | `this.data.showLocations` — js:350,1178,944,490 | page default for the locations toggle (`'1'` = on) |
| `data-gl` | section-map.html:30 | `el.dataset.gl` — js:2796 (`init`) | opt-out flag: if set, the Leaflet `init()` skips this container entirely (reserved for the MapTiler GL spike to claim it instead) |
| `data-rendered` | set by script only (js:926,2802) | `el.dataset.rendered` — js:2796 | marks a container already initialized/adopted; not server-rendered |

Note: `id="section-map-{{ map_config.year }}"` (section-map.html:2) — id changes per year, read back by `adopt()` (`this.el.id = newEl.id`, js:927).

### 1.2 Elements found by selector

All under `.section-map-wrap` (`attachControls`, js:385-467), re-queried on every `attachControls()` call (page load and every `adopt()`):

- `.section-map-wrap` — `this.el.closest('.section-map-wrap') || this.el.parentNode` (js:386)
- `.section-map-toolbar` — `this.toolbarEl` (js:388); unhidden at js:395
- `.section-map-controls` — `this.controlsEl` (js:389) — the Options dropdown body
- `.section-map-legend-panel` — `this.legendPanelEl` (js:390); unhidden at js:396
- `.section-map-legend` — `this.legendEl` (js:391) — the `<ul>` legend rows target
- `.section-map-level` — `this.levelEl` (js:392) — the level-note `<span>`
- `.section-map-status` (inside `.section-map-controls`) — `this.statusEl` (js:393)
- `input[name="metric"]` (radios, inside `.section-map-controls`) — js:399-403
- `input[name="notices"]` — js:405-409
- `input[name="locations"]` — js:411-415
- `select[name="tiles"]` — js:419-429 (options populated from `TILE_STYLES`)
- `select[name="ramp"]` — js:430-440 (options populated from `RAMPS` keys)
- `select[name="bins"]` — js:441-451 (options populated from `BIN_OPTIONS`)
- `input[name="sections"]` — js:453-457 ("All sections" toggle)
- `.section-map-expand` — js:460-464 (expand/compress button)
- `.section-map-panel[data-panel]` — `bindPanelToggles`, js:552-561 (both the legend panel and, on pages that have one, any other `data-panel` panel)
- `.section-map-panel-toggle` (inside each panel) — js:556
- `.section-map-toolbar` again inside `bindToolbar` (js:475), with:
  - `.dropdown` (all toolbar dropdowns, filters + Options) — js:478
  - `.dropdown-trigger .button` — js:499,506
  - `.dropdown-menu` — js:520
  - `.section-map-toolbar-filters` (the filter `<form>`, `map-toolbar.html:9`) — js:484, wired to `htmx:configRequest`
  - `input[type="search"], select` inside an opened dropdown — js:515 (focus on open)
- `.section-map-locations-note` — `updateLocationsNote()`, js:2076
- `.explorer-scope-bar` (document-level, not wrap-scoped) — `fitBelowNavbar()` js:589, `setExpanded()` js:623
- `nav.navbar` (document-level) — `fitBelowNavbar()` js:584

### 1.3 CSS classes the script toggles

- `.is-active` on a `.dropdown` — toolbar dropdown open/closed (js:511-513); closed on outside click / Escape (js:525-528)
- `aria-expanded` attr (not a class) mirrors `.is-active` on the trigger button
- `.is-collapsed` on a `.section-map-panel` — panel folded state (`setPanelCollapsed`, js:569-573), persisted per-panel-name in `localStorage` (`readPanelState`/`writePanelState`, js:536-550, key prefix `pesticides:section-map:panel:`)
- `.section-map-expanded` on `document.documentElement` (`<html>`) — expanded mode, toggled first so `fitBelowNavbar` can measure the pinned scope bar (js:616)
- `.is-expanded` on `.section-map-wrap` — expanded mode on the wrapper (js:618)
- `aria-pressed`, `title`, `aria-label` on `.section-map-expand` reflect expanded state (js:638-642)
- `data-bound="1"` markers (not styling, re-bind guards) on `.section-map-expand`, `.section-map-toolbar`, each `.dropdown-trigger`-owning toolbar, each `.section-map-panel-toggle`

CSS response to these (`assets/css/pesticides/section-map.css`):
- `.section-map-wrap.is-expanded` → `position: fixed; top: calc(var(--navbar-height) - 1px); ...; z-index: 25` (css:190-200); `.section-map` inside it goes full-height, border removed (css:202-207)
- `html.section-map-expanded, html.section-map-expanded body` → `overflow: hidden` (css:209-212)
- `html.section-map-expanded .explorer-scope-bar` → `position: fixed; top: var(--navbar-height); z-index: 1010` pinning it under the navbar, with its own bottom border (css:216-223) — `top` is refined at runtime by `fitBelowNavbar()` (js:591, inline style)
- `.section-map-panel.is-collapsed` → removes `.section-map-panel-head` bottom border (css:36-38), hides `.section-map-panel-body` (css:93-95), rotates `.section-map-panel-chevron` 180deg (css:85-87)
- `.section-map-toolbar-dropdown.is-set .button` (server-rendered class, not script-toggled — see map-toolbar.html:14) → highlighted border/text color (css:442-445) when a chemical/product/commodity filter is active
- `.section-map-expand .is-compress` / `.is-expand` spans — both rendered, CSS shows the right one via `.section-map-wrap.is-expanded .section-map-expand .is-compress { display: inline-flex }` vs. the default hiding `.is-compress` and, when expanded, hiding `.is-expand` (css:469-476) — worked around like this because the icon font swaps `<span>`s for inline SVG, so JS can't just toggle a class on one icon
- `.section-map-locate.is-locating` — geolocation in progress, pulsing icon animation (css:382-395)

## 2. URL query params (`window.location.search`)

All parsed with ad-hoc regexes against `window.location.search` at construction time (not re-read later), except where noted. Written back only via `syncViewParams()` (js:1163-1209), which uses `history.replaceState` (never `pushState` — no new history entries) and is called after every control change.

| param | read | write | default / notes |
|---|---|---|---|
| `?metric=lbs_chemical\|applications` | js:340-341 (`metricMatch`) | `syncViewParams` js:1167-1171 | default `lbs_chemical`; omitted from URL when default |
| `?notices=0\|1` | js:345-346 (`noticesMatch`) | `syncViewParams` js:1172-1177 | overrides `data-show-notices` page default; omitted when equal to page default |
| `?locations=0\|1` | js:349-350 (`locationsMatch`) | `syncViewParams` js:1178-1183 | overrides `data-show-locations`; omitted when equal to page default |
| `?sections=1` | js:353 (`/[?&]sections=1/.test(...)`, boolean presence test only, no off value) | `syncViewParams` js:1184-1188 | "All sections" mode; any other value / absent = off |
| `?tiles=<style>` | js:694-696 (`tilesMatch`), constrained to `[a-z0-9-]+` | `syncViewParams` js:1190-1194 | experiment control; default derived from `data-tiles` URL's own `/maps/<style>/` segment (js:695); omitted when equal to that default |
| `?ramp=<name>` | js:54-55 (`rampMatch`, module-scope, evaluated once at script load) | `syncViewParams` js:1195-1199 | must match a `RAMPS` key or falls back to `RAMPS.blues`; `this.rampName` set in `onRampChange` (js:1146) — note: not initialized from the URL into `this.rampName` at construction, so a page loaded with `?ramp=` set but never changed via the UI won't echo it back via `syncViewParams` until the user touches the ramp select (the module-level `RAMP` is correct on load either way) |
| `?bins=4\|5\|6\|8\|10` | js:59-61 (`binsMatch`), validated against `BIN_OPTIONS` | `syncViewParams` js:1200-1204 | default `DEFAULT_BINS = 6`; same as ramp, `this.bins` only set on `onBinsChange` (js:1154), not from the URL at construction |

Params read/written elsewhere but not part of the map's own view state:
- `year`, `county`, `concern`, `chemical`, `product`, `commodity` — page-level scope/filter params, read server-side into `map_config` (`section_map_config`) and re-submitted by the filter form (`map-toolbar.html`) and `scope-hidden.html`; the map script only reads them back off `data-*` (`commonParams()`, js:1211-1220), it does not parse them from the URL itself.
- Lat/lng/zoom are **not** URL params for this map — they come from `data-center`/`data-zoom` (server-rendered) only; there is no `?lat=&lng=&zoom=` read/write anywhere in `section-map.js`.

No param is ever removed except via the default-comparison logic in `syncViewParams`; unrecognized/foreign query params on the page are left untouched (the code only calls `.set`/`.delete` for its own six keys).

## 3. Layers and z-order

### 3.1 Panes (created in `init()`, js:704-754), lowest to highest z-index

| pane | z-index | created at | holds |
|---|---|---|---|
| (default Leaflet `tilePane`) | ~200 | implicit | `L.tileLayer` base map (js:719-723) |
| (default `overlayPane`) | 400 | implicit | `gridLayer` (section/township geoJSON, no explicit pane — js:2122), `outlineLayer` is explicit-pane (below), radius circle (`L.circle`, no pane — js:902) |
| `pesticide-lens` | 410 | js:748-749 | lens section layer (js:1971-1994) and "all sections" canvas layer (js:1824-1826) — both drawn "just above the township fills" |
| `pesticide-lens-outline` | 415 | js:752-754, `pointerEvents: none` | the hovered township's redrawn outline while the lens is up (`drawLensOutline`, js:1691-1702) |
| `pesticide-counties` | 420 | js:729-730 | county outline layer (js:1025-1029) |
| `pesticide-outline` | 430 | js:742-743 | the page's own region outline (city/ZIP/place), js:1076-1080 |
| `pesticide-locations` | 440 | js:737-738 | schools/child care circle markers (js:2571-2591) |
| `pesticide-notices` | 450 | js:732-733 | notice-of-intent circle markers (js:2435-2450) + the locate-me dot (`showLocation`, js:861-869, reuses this pane) |

Full bottom-to-top order: tiles → grid/radius (`overlayPane` 400) → lens (410) → lens-outline (415) → counties (420) → outline (430) → locations (440) → notices (450). Matches the code comment at js:735-736 ("Schools and child care sit just under the notice markers"): a notice always wins an overlap with a school/child-care marker.

Leaflet's built-in `zoomControl` (topleft) plus the custom Locate (js:782-803) and Reset (js:807-826) controls stack in normal Leaflet control layering, unaffected by panes.

### 3.2 Layers, one at a time, and their data sources

- **`gridLayer`** — one of township or section GeoJSON, mutually exclusive (`this.level`). Source: `data.sectionsUrl` (`loadSections`, js:1325-1379) or `data.townshipsUrl` (`loadTownships`, js:1381-1430), each with `commonParams()` (year/chemical/product/commodity/county/concern) + `bbox=` (padded viewport, `fetchBounds`). Townships additionally send `geometry=0` when a values-only refetch is possible (js:1393).
- **`countiesLayer`** — `data.countiesUrl`, fetched once, no params (js:1016-1035).
- **`outlineLayer`** — `data.outlineUrl`, a regions-API JSON payload; `payload.data.boundary.geometry` is drawn (js:1064-1086).
- **`noticesLayer`** — `data.noticesUrl` with `bbox`, `chemical`, `product`, `county` (js:2375-2421).
- **`locationsLayer`** — `data.locationsUrl` with `bbox`, `county` (js:2508-2557).
- **`lensLayer`** — sections for the hovered township's 3x3 neighborhood, drawn from `lensCache` (populated by `fetchLensSections` hitting `data.sectionsUrl` with a union bbox of the 3x3 or 5x5 townships + `commonParams()`), js:1568-1994.
- **`allSectionsLayer`** — same section data source, drawn on a canvas renderer, accumulated across 5x5-township blocks (js:1736-1868).
- **`radiusCircle`** — no fetch; drawn from `data.radius` around `data.center` (js:895-904).
- **`locationMarker`** — no fetch; the browser geolocation result (js:857-869).

### 3.3 Styling rules

**Grid cells** (`featureStyle`, js:1466-1490):
- "All sections active" (allSectionsActive() true, i.e. `showAllSections && level==='township'`): township polygons render invisible/non-interactive-looking (`fillOpacity: 0, stroke: false, fillColor: NO_DATA_COLOR`) — they still exist for hover/click plumbing but the all-sections canvas layer visually replaces them.
- Otherwise: `fillColor: colorFor(currentClasses, value)`; `fillOpacity: 0.7` if value truthy else `0.25` (no-data wash); `stroke: true`; `color/opacity` from `GRID_LINE` (`#1f2d3d` @ 0.18); `weight: 0.75` at township level, `0.5` at section level.
- Selected section (`isSelected`) → merges `SELECTED_LINE` (`stroke:true, color:#1f2d3d, opacity:0.9, weight:1.5`).
- Highlighted (page's own section, `isHighlighted`) → `color:#d35400` (orange), `opacity:1`, `weight:3`.

**Hover** (`hoverStyle`, js:1498-1502): weight `2.5` (township) / `2` (section); `color:#999` if the cell has no value for the current metric, else `#222`; always `opacity:1, stroke:true`. Lens cells use `lensHoverStyle` (js:1504-1506): same weight-2, colour `#111` w/ data else `#999`.

**Lens/all-sections cells** (`lensSectionStyle`, js:1922-1951): `fillColor` from quantile classes; `fillOpacity` `0.85` w/ value else `0.35`; base stroke `GRID_LINE` @ weight `0.5`. Below `SECTION_LINES_MIN_ZOOM` (10): no-data cells get `fillOpacity:0, stroke:false` (fully invisible rather than a pale wash); cells with data instead get a **hairline seam stroke in the fill's own colour** (`style.color = fill; style.opacity = fillOpacity; style.weight = 1`) to close antialiasing gaps between canvas-rendered neighbouring polygons. Selected section still overlays `SELECTED_LINE` on top of either branch.

**County outline** (`countyStyle`, js:1004-1013): `color: COUNTY_COLOR (#1f2d3d)`, `weight:1.5`, `fill:false`, `opacity:0.8`; `dashArray:'4 3'` once zoomed to section level (`atSectionZoom()`), solid otherwise — recomputed on every `zoomend` (`restyleCounties`, js:1088-1090, bound js:765).

**Region outline** (`loadOutline`, js:1079): fixed style — `color:'#d35400', weight:2.5, opacity:0.9, fillColor:'#d35400', fillOpacity:0.08`.

**Radius circle** (`drawRadius`, js:895-904): default Leaflet circle style (no explicit style object passed — just `interactive:false`), sized by `radiusMiles * 1609.34` meters, then `fitBounds` to it.

**`SECTION_LINES_MIN_ZOOM` (10) behaviour**: gates the lens/all-sections hairline-seam vs. invisible-no-data logic above; toggled by `restyleSectionLines()` (js:1872-1883), bound to `zoomend` (js:767), which re-styles every layer in `allSectionsLayer` and fully clears the lens (`clearLens()`) on crossing the threshold (so a stale lens style doesn't linger). It is independent of `SECTION_ZOOM`/`sectionZoom()` (grid-level threshold) — sections can be drawn (via lens/all-sections) at township zoom levels well below `SECTION_LINES_MIN_ZOOM`.

## 4. Zoom logic

- **`SECTION_ZOOM = 11`** (js:21) — the floor: at this zoom or closer, sections are drawn instead of townships, provided the viewport isn't too wide (see `sectionZoom()`).
- **`sectionZoom()`** (js:1228-1237) — computes the *effective* zoom-in threshold for the current viewport: starting at `SECTION_ZOOM`, walks upward (zoom 11..17) computing `milesPerPx = 156543.03 * cos(lat) / 2^zoom / METERS_PER_MILE` (Web Mercator ground resolution) and `squareMiles = width_px * height_px * milesPerPx^2`; returns the first zoom where `squareMiles <= MAX_VIEWPORT_SECTIONS`, or `18` if none qualify. So a wide/tall viewport (e.g. the expanded map) needs to zoom in further than 11 before sections load, to keep the section count the API would return under the cap.
- **`MAX_VIEWPORT_SECTIONS = 2000`** (js:24) — the section-count budget for the viewport-based threshold above; kept under the API's 2,500-section cap (comment js:22-23) leaving headroom for the padded (`BBOX_PAD`) fetch.
- **`atSectionZoom()`** (js:1239-1241) — `map.getZoom() >= sectionZoom()`; the single predicate used everywhere to decide section-vs-township (`loadGrid`, `countyStyle` dash, etc).
- **Township vs section levels**: `loadGrid()` (js:1243-1265) computes `level = atSectionZoom() ? 'section' : 'township'` on every `moveend`/`zoomend` (debounced 300ms, `DEBOUNCE_MS`). Crossing the section/township boundary always refetches (`level === this.loadedLevel` check, js:1255, fails); staying within the same level and viewport already `covers()`ed skips the fetch (with an "all sections" top-up, js:1257, if that mode is on).
- **`covers(bounds)`** (js:1269-1271) — `bounds.contains(map.getBounds())`; used to decide whether the last padded fetch already spans the new viewport, for grid (js:1255), notices (js:2380) and locations (js:2522) loads independently (each tracks its own `loadedBounds`/`loadedNoticeBounds`/`loadedLocationBounds`).
- **`geometry=0` values-only refetch** (townships only, js:1391-1413): once township outlines have been fetched and cached (`rememberTownshipGeometry`, js:1432-1439, keyed by feature id, remembering the bounds they were fetched for), a subsequent township fetch whose bbox is still covered by that cached-geometry bounds (`townshipGeometryCovers`, js:1441-1443) sends `geometry=0` and gets back properties only; `attachTownshipGeometry()` (js:1447-1456) splices the cached geometry back onto each feature by id, returning `false` (triggering one full, non-values-only refetch) if any feature in the response isn't in the cache (e.g. a wider bbox reaching new townships).
- **`fetchBounds(unpadded)`** (js:1301-1304) — `map.getBounds()`, padded by `BBOX_PAD = 0.5` (half a viewport) on each side unless `unpadded` is passed; used for sections, townships, notices, and (conditionally) locations. Rationale (comment js:137-140): without padding, opening a popup near the edge auto-pans the map, which would otherwise refetch and rebuild layers out from under the popup.
- **400 fallback chain for sections** (`loadSections`, js:1346-1358): a 400 from the padded fetch retries once unpadded (`loadSections(true)`); a 400 from the unpadded fetch falls back to `loadTownships()` rather than leaving the map bare.
- **`startGridRequest()`** (js:1318-1323) — one `AbortController` shared by both section and township requests; starting a new one aborts whichever of the two was in flight, since deciding to draw the other level makes the pending one stale.

## 5. The lens

### 5.1 Trigger and neighborhood

- Trigger: `mouseover` on a township-level grid cell (`bindHover`, js:1508-1532), but only when not in "all sections" mode (js:1511) and only at `level === 'township'` (js:1512). Calls `showLens(feature, layer)` if the hovered township differs from `this.lensId` (js:1514).
- **`neighborhoodOf(layer, reach)`** (js:1545-1566) — the Moore neighborhood: every township on `gridLayer` whose bounds-center is within `reach` townships (in `TOWNSHIP_DEGREES` units, `{lat:0.087, lng:0.108}`) of the hovered layer's bounds-center, on both axes independently (`Math.abs(dx) <= maxDx && Math.abs(dy) <= maxDy`), floored at a full township size to handle partial/edge townships. Reach `1.5` (default, js:1548) → the 3x3 block; reach `2.5` → the 5x5 ring used for prefetch.
- Comment (js:1549-1553) explains why center-distance rather than bounds-intersection is used: diagonal neighbors only touch at a corner, and survey offsets between ranges leave gaps that an intersection test would drop.

### 5.2 Fetch + cache

- **`lensCache`** (js:755, initialized `{}` in `init()`; reset to `{}` in `adopt()` on `dataChanged`, js:986) — keyed by **township id** (not section id): `lensCache[townshipId] = [section features]`.
- **`LENS_FETCH_DELAY_MS = 50`** (js:31) — `showLens()` (js:1568-1598): if every neighborhood township id is already cached (`uncached(ids).length === 0`, js:1607-1610), draws immediately; otherwise waits 50ms (`lensFetchTimer`) before fetching, so a cursor sweeping across townships doesn't fire a fetch per township passed over — only the one it rests on.
- **`fetchLensSections(hosts, done)`** (js:1616-1646) — one request per neighborhood: bbox is the union of the hosts' bounds, `commonParams()` + that bbox, hits `data.sectionsUrl`. Response features are bucketed back to their owning township by parsing `section.properties.mtrs` and taking everything before the last `-` (the MTRS minus the section suffix) — `mtrs.slice(0, mtrs.lastIndexOf('-'))` (js:1639). Filed into `this.lensCache` **captured at fetch start** (`var cache = this.lensCache`, js:1630) — so if `adopt()` swaps in a fresh cache mid-flight (filter change), the old fetch's results land in the discarded cache object and are silently dropped, never polluting the new cache.
- **`openLensId`** (js:373, set/cleared by `trackPopup`, js:2101-2107, called for each lens section layer at js:1991) — while a lens section's popup is open, `showLens()` refuses to redraw the lens for a different township (js:1573: `if (this.openLensId) return;`), i.e. the lens is pinned.

### 5.3 Prefetch ring

- **`prefetchRing(layer)`** (js:1653-1673) — after drawing a lens, schedules (via `requestIdleCallback` with a 500ms timeout, or `setTimeout(..., 150)` fallback) a fetch for the 5x5 ring minus the 3x3 inner block minus anything already cached. Guarded by `this.prefetching` so only one prefetch runs at a time; if the lens has moved on by the time the idle callback runs, it prefetches around the *current* neighborhood instead (re-reads `neighborhoodOf` fresh, js:1658-1660).

### 5.4 Drawing, outline, classing

- **`drawLens(id, features)`** (js:1957-1995): removes any existing `lensLayer`; if there are no features for this township+ring, returns early leaving nothing drawn (i.e. townships with zero sections in the response just show no lens). Otherwise calls `setHostFills(false)` (js:1678-1686) to zero out the 9 host townships' own fill (so the lens shading isn't stacked under the section shading), computes fresh **quantile classes over only the lens's own features** (`this.lensClasses`, independent of `this.currentClasses`/the main legend), and builds an `L.geoJSON` on the `pesticide-lens` pane styled via `lensSectionStyle(section, classes)`.
- **Lens outline** (`drawLensOutline`, js:1691-1702): draws the hovered township's own polygon outline on the separate `pesticide-lens-outline` pane (z 415, above the lens fills at 410) using `hoverStyle(feature)`, only when the township has data and only while the lens shows (called from `setHostFills(visible)` as `drawLensOutline(!visible)`, js:1685).
- **Lens hover/click**: each lens section gets `mouseover` → `cancelLensClear()` then `recentreLens(section)` (js:1707-1718, moves the lens if the pointer entered a different township's own section) else `lensHoverStyle`; `mouseout` → restyle to `lensSectionStyle` + `scheduleLensClear()`; `click` → `showSectionPopup`; `popupclose` → `scheduleLensClear()` too (js:1974-1993).

### 5.5 Clearing delays and popup interaction

- **`scheduleLensClear()`** (js:1997-2013) — 120ms grace timer; on fire, keeps the lens if `openLensId` is set (a section popup is open) or if the lens was redrawn (recentred) after the clear was scheduled (`lensDrawnAt >= scheduledAt`, guards against a mouseout that came from a section the recenter already removed). Triggered from: leaving a township cell while `lensId` still matches it (js:1524-1528, "may be moving onto one of this township's own sections"), leaving a lens section (js:1985), and a lens section's `popupclose` (js:1992).
- **`cancelLensClear()` / `cancelLensFetch()`** clear the respective timers; called on re-entry / redraw.
- **`clearLens()`** (js:2022-2034): cancels both timers, nulls `lensId`/`openLensId`, restores host township fills (`setHostFills(true)`), and removes `lensLayer` from the map. Called on: leaving township level, toggling "all sections" on (js:659), a data change in `adopt()` indirectly via cache reset, `restyleSectionLines()` crossing `SECTION_LINES_MIN_ZOOM` (js:1882), and a ramp/bins change while a lens is up (js:1148,1156).

### 5.6 "All sections" mode

- Enabled by the `sections` checkbox (`onSectionsToggle`, js:655-664) or `?sections=1`; only meaningful at township zoom (`allSectionsActive()`, js:1462-1464: `showAllSections && level === 'township'`); the checkbox itself is disabled when `level === 'section'` (js:2065).
- **`loadAllSections()`** (js:1736-1795): tiles the *visible* townships (`visibleTownships()`, js:1726-1734, viewport padded by 0.15) into fixed **5x5-township blocks** keyed by `floor(lng / (TOWNSHIP_DEGREES.lng*5)) : floor(lat / (TOWNSHIP_DEGREES.lat*5))` (a stable grid independent of viewport position, js:1745-1756), skipping townships already in `lensCache`. Draws whatever's cached immediately (`drawAllSections()`), then fetches remaining blocks with concurrency `ALL_SECTIONS_CONCURRENCY = 4` (js:33), reusing `fetchLensSections` — so lens and all-sections share one cache and one fetch path.
- A `run` token (`{total, done}`) supersedes any in-flight run when a new `loadAllSections()` starts (e.g. pan while blocks are loading); stale callbacks check `self.allSectionsRun !== run` and bail, though already-started fetches still finish and land in the (shared) cache.
- Status line shows `"Loading sections… N of M"` (`setStatus`, js:1777,1793) while blocks load, cleared on completion.
- **Drawing** (`drawAllSections`, js:1817-1868): builds the layer once (canvas renderer `L.canvas({pane:'pesticide-lens'})`, js:1821) and only ever grows it (`addData`) — never rebuilt/re-parsed — for perdorming reasons (comment js:1813-1816: rebuilding cost more than the network requests). First batch of sections in triggers classing over just what's loaded so far so nothing draws unshaded (js:1860-1865); the township grid's own cells switch to invisible via `featureStyle`'s `allSectionsActive()` branch (js:1845) the moment the layer is created.
- **Classing over the block**: `restyleAllSections()` (js:1885-1893) recomputes quantile classes over **all accumulated `allSectionsFeatures`** (not just visible ones) and restyles every layer + the legend; throttled while blocks are still landing via `scheduleAllSectionsDraw()` (`ALL_SECTIONS_REDRAW_MS = 600`, js:35, 1797-1811) and always run once more when the last block lands (js:1786-1787).
- **Click/hover on all-sections cells**: same `lensHoverStyle`/`lensSectionStyle`/`showSectionPopup` wiring as the lens (js:1828-1841), tracked via `trackPopup(..., 'openAllSectionsId')`.
- **Clearing**: `clearAllSections(keepFlag)` (js:1898-1913) — removes the layer, drops the canvas renderer, resets accumulation state; `keepFlag=true` (used when crossing into section zoom, js:1249) leaves the `showAllSections` toggle on since the mode is just moot at that zoom, not turned off.
- **Legend change**: while all-sections is active, `legendUnit()` (js:2036-2039) returns the *section* unit (not "per township") since `allSectionsActive()` excludes the township suffix; `updateLegend()`'s level-note text switches to `LEVEL_TEXT.allSections` ("Each square is one square-mile section, across every township in view.", js:154) instead of the plain township text.

## 6. Quantile classing, ramps, legend

### 6.1 `quantileClasses(values)` (js:248-274)

Mirrors `camp.apps.pesticides.maps.quantile_classes` server-side (comment js:245-247). Algorithm:
1. Filter to truthy (`values[i]` truthy — so `0`/`null`/`undefined` all excluded as "no data") values → `positive`.
2. Sort ascending, dedupe to `distinct`.
3. If no distinct values, return `{breaks: [], colors: [], members: []}` (empty legend).
4. `count = min(NUM_CLASSES, distinct.length)` — fewer classes than requested when there aren't enough distinct values.
5. Break points: for `k` in `1..count`, `position = ceil(k * distinct.length / count) - 1`, `breaks.push(distinct[position])` — standard quantile cut method.
6. `colors = sampleRamp(RAMP, count)`.
7. `members[i]` = every positive value whose `indexFor(breaks, value)` is `i` (js:276-281, first break `value <=` — i.e. inclusive upper bound per class), used only for the legend's low/high range display, not styling.

### 6.2 Bins / classes options

- `NUM_CLASSES` (js:61, module-level, mutable) — set from `?bins=` at load (`binsMatch`, js:59-61) validated against `BIN_OPTIONS`; changed live via the bins `<select>` (`onBinsChange`, js:1152-1158, also clears the lens if open).
- `BIN_OPTIONS = [[4,'Quartiles'],[5,'Quintiles'],[6,'Sextiles'],[8,'Octiles'],[10,'Deciles']]` (js:58).
- `DEFAULT_BINS = 6` (js:60) — Sextiles.

### 6.3 Ramps

- `RAMPS` (js:37-53) — 12 named 5-stop hex arrays: `blues` (default), `purd`, `bupu`, `ylorbr`, `putrid`, `bile`, `putrid2`, `ylgnbu`, `pubugn`, `mako`, `cividis`. Several are annotated in comments as experimental/candidate (`putrid`/`bile`/`putrid2` explicitly "while we pick one").
- `RAMP` (js:55, module-level, mutable) — selected from `?ramp=` at load (`rampMatch`, js:54) or defaults to `RAMPS.blues`; changed live via the ramp `<select>` (`onRampChange`, js:1142-1150, also clears the lens if open).
- `NO_DATA_COLOR = '#f0f0f0'` (js:56) — used whenever `colorFor` gets a falsy value or there are no breaks at all.
- **`sampleRamp(ramp, count)`** (js:65-78) — resamples a 5-stop ramp to `count` evenly-spaced colors by linear RGB interpolation between adjacent stops (`t = i*(stops.length-1)/(count-1)`, floor/ceil stops, `f` fractional blend); `count <= 1` returns just the ramp's darkest stop.
- **`colorFor(classes, value)`** (js:283-286) — `NO_DATA_COLOR` if `!value || !classes.breaks.length`, else `classes.colors[indexFor(classes.breaks, value)]`.

### 6.4 Legend rendering

- **`renderLegend(el, classes, unit)`** (js:288-309) — clears `el`, then one `<li>` per non-empty class (`swatch` colored square + `low–high unit` or `low unit` range text if `low===high`), plus a final fixed `<li>` for "No data" swatched `NO_DATA_COLOR`.
- **Unit labels**: `METRIC_UNITS = {lbs_chemical: 'lbs', applications: 'applications'}` (js:127-130); `legendUnit()` (js:2036-2039) appends `' per township'` when `level === 'township'` and all-sections mode is *not* active.
- **`updateLegend()`** (js:2058-2070) — calls `renderLegend` then `appendMarkerLegend()`; also disables the "All sections" checkbox at section level, sets the level-note text (`LEVEL_TEXT[level]` or `.allSections` variant), and calls `updateLocationsNote()`.
- **Marker legend rows** (`appendMarkerLegend`, js:2043-2056) — appended *after* the quantile swatches, as `<li class="is-marker">` rows with a dot swatch (`.is-dot`, styled by CSS as round) rather than a square: `MARKER_LEGEND` (schools, child care) when `showLocations`, plus a synthesized `{color: NOTICE_COLOR, label:'Notice of intent'}` row when `showNotices`.
- **`LEVEL_TEXT`** (js:151-155): `section` → "Each square is one square-mile section."; `township` → "Each square is a 6 × 6 mile township; zoom in for square-mile sections."; `allSections` → "Each square is one square-mile section, across every township in view."

## 7. Popups

### 7.1 Shared popup mechanics

- **`POPUP_OPTIONS`** (js:145-149): `maxWidth: 320`, `autoPanPadding: [24, 24]`, `closeButton: true`.
- **`popupOptions(className)`** (js:2221-2223) merges `{className}` on top — every popup type gets its own outer class (`section-popup-wrap`, `notice-popup-wrap`).
- **`openPopupAtCenter(layer)`** (js:203-210) — overrides Leaflet's default (popup opens at click point) so a grid cell's popup rises from the cell's bounds-center instead (`layer.getBounds().getCenter()`); applied to township (`bindTownshipPopup`, js:2230) and section (`showSectionPopup`, js:2343) popups, not to notice/location point markers (those are already points, `bindPopup` default is fine).
- **`closePopupOnClick: false`** — set once on `L.map(...)` construction (js:704): a popup persists across a click on empty map or a pan that lands with it inside the frame; only its own close button, or opening a different popup, dismisses it. Comment (js:702-703) frames this as deliberate.
- **`trackPopup(layer, id, key)`** (js:2101-2107) — generic: on `popupopen` sets `this[key] = id`; on `popupclose`, if `this[key]` still equals `id`, nulls it. Used for `openGridId`, `openNoticeId`, `openLocationId`, `openLensId`, `openAllSectionsId` — each layer type remembers which feature's popup is open so a rebuild (refetch/restyle) can reopen it (`reopenGridPopup` js:2152-2163, `renderNotices`/`renderLocations` reopen-by-id at js:2452-2456/2593-2597).
- **`bindZoomButtons()`** (js:2236-2260) — a single delegated `popupopen` listener (bound once, in `init()`) attaches a click handler to each popup's outer DOM element (once, guarded by `data-zoom-bound`) rather than per-button, because `setPopupContent`/restyle replaces the inner HTML (and Leaflet stops propagation at the popup wrapper, so a page-level delegated handler can't reach inside it either — comment js:2233-2235). Handles clicks on `.section-map-zoom` buttons: reads `data-lat`/`data-lng` (and optional `data-id` for a section-in-lens zoom-in), sets `self.openGridId = sectionId` so the reload at the new zoom reopens that section's popup, or closes the popup outright for a plain township zoom-in, then `map.setView([lat,lng], sectionZoom(), {animate})`.

### 7.2 Township popup

- **Content** (`townshipPopupHtml`, js:2205-2219): `<h4>` name/id, subline `"Township · N square-mile section(s)"`, `metricLine(props)` headline, then a "Zoom in to sections" button (`.section-map-zoom`, carrying `data-lat`/`data-lng` of the popup's own center, no `data-id`).
- Bound via `bindTownshipPopup` (js:2225-2231): `layer.bindPopup(html, popupOptions('section-popup-wrap'))` + `openPopupAtCenter(layer)`; wired in `renderGrid`'s `onEachFeature` only when `level === 'township'` (js:2130-2133).
- **Zoom-in button**: see 7.1 `bindZoomButtons` — no `data-id`, so it just zooms and lets the section grid load fresh at the new spot (no popup carried over).
- **Restyle refresh**: `restyle()` (js:2165-2185) — for the township level, if a layer's popup exists (open or previously bound), its content is regenerated via `townshipPopupHtml` on every metric change etc. (js:2175-2177), so the headline figure stays in sync with the current metric even while the popup is open.

### 7.3 Section popup

- **Content** (`sectionPopupHtml`, js:2267-2287): `<h4>` MTRS/id, subline `"Square-mile section · County"`, `metricLine`, a "Top chemicals" label + `detailHtml` (see below), and action links: "Section details" (`data.sectionPageUrl`) always if present; a "Zoom in" `.section-map-zoom` button *only* when `center` was passed **and** `this.level === 'township'` — i.e. only for a section popup opened from inside the lens/all-sections at township zoom (comment js:2264-2266: the township popup is unreachable there since the lens sections cover it, so its zoom-in action rides on the section popup instead). That button carries `data-id` (the section id) so `bindZoomButtons` sets `openGridId` for reopening after the zoom.
- **`showSectionPopup(feature, layer)`** (js:2338-2373): opens the popup immediately with a "Loading…" chemicals placeholder, calls `selectSection(id, layer)` (outlines it, see 7.3.1), then fetches `data.sectionUrlPattern` (with `{id}` filled + `?year=`) for `detail.top_chemicals`; on success rebuilds content with up to 3 chemicals (`chemicals.slice(0,3)`) each showing name (linked, `.is-of-concern` dot if flagged) and `lbs` amount; guards every content update with `layer.getPopup() && layer.isPopupOpen()` so a closed popup doesn't get a late write.
- **`metricLine(props)`** (js:2196-2203) — shared headline formatter for both township and section popups: `"<strong>N lbs</strong> applied{year phrase}"` or `"<strong>N</strong> application(s){year phrase}"` depending on `this.metric`. `yearPhrase()` (js:2188-2192) renders `" in {year_label}"` or `" across {year_label}"` for `data-year="all"`.

#### 7.3.1 Selected-section outline & persistence

- **`selectSection(id, layer)`** (js:2292-2310) — sets `this.selectedSectionId`, restyles the layer (adds `SELECTED_LINE`), brings it to front, and (once per layer, guarded by `layer._selectionBound`) binds a `popupclose` handler that clears the selection **only if the layer is still on the map** (`map.hasLayer(layer)`) — a grid rebuild that removes the layer also fires `popupclose`, but that's not "the reader letting go," so the selection outlives it.
- **`reopenSelectedSection(group)`** (js:2314-2323) — after any group of section layers is (re)built (`renderGrid` for the section grid, `drawAllSections` for all-sections), finds the feature matching `selectedSectionId` and reopens its popup if not already open. This is how the orange/dark selection outline and open popup survive a refetch, a zoom crossing into a different level, or new all-sections blocks landing.
- **`restyleSection(layer)`** (js:2327-2336) — re-applies whichever style function owns the layer (`featureStyle` for the main grid, `lensSectionStyle` with `lensClasses` for the lens, or with `currentClasses` for all-sections) — used by `selectSection`'s deselect path.
- Not persisted across an `adopt()` data change: `dataChanged` branch in `adopt()` doesn't preserve `selectedSectionId` explicitly, but since `loadGrid()`/`renderGrid()` re-fetches and `reopenSelectedSection` is called from `renderGrid` unconditionally when `level==='section'` (js:2144), a selection would only reappear if the same section id still exists in the new response — otherwise it silently has no effect (no explicit clear).

### 7.4 Notice popup

- **Content** (`noticePopupHtml`, js:2461-2506): `<h4>` scheduled-application datetime + an "Active" tag/badge; subline `"Notice of intent · County · Section"` (section linked via `section_id`→`sectionUrl`); optional headline combining `treated_amount treated_units by application_method` (or whichever half is present); "Products" and "Chemicals" labelled lists (each item a link, chemicals get the `.is-of-concern` dot); action pills: "Full notice" (`data.noticePageUrl`) if `props.id`, plus a permanent external "Sign up with SprayDays" link to `SPRAYDAYS_URL = 'https://spraydays.cdpr.ca.gov/'` (js:125) opened `target="_blank" rel="noopener"`.
- Bound in `renderNotices`'s `onEachFeature` (js:2446-2449): `trackPopup(..., 'openNoticeId')` + `bindPopup(noticePopupHtml(...), popupOptions('notice-popup-wrap'))`. No custom open-at-center behaviour (point marker, default is fine) and no lazy-loaded detail fetch — all content comes from the GeoJSON properties already fetched.

### 7.5 Location popup (school / child care)

- **Content** (`locationPopupHtml`, js:2720-2766): `<h4>` title-cased name (`titleCaseName`, see below); subline built from `type_label` + address/city (title-cased), falling back to `school_district` if neither address/type present; headline is one of three states keyed by `block` param: `undefined` → "Loading nearby use…", `null` → "Couldn't load nearby use.", object → `metricLine`-style headline ("N lbs applied within about a mile{year phrase}" or "N application(s)…"); action pills: "Section details" (only if the computed block has a `section.id`) and **"District page"** (`props.school_district_url`, only if present) — the pill referenced by the spec as `data-*`-carried is literally `school_district_url` on the GeoJSON feature.
- **Lazy 3x3 totals** (`loadLocationBlock`, js:2668-2697): fired on `popupopen` (js:2587-2589, not eagerly with the marker fetch), requests `data.sectionsUrl` with `commonParams()` + `bbox = blockBbox(latlng)` (a padded bbox guaranteed to cover the 3x3-mile block around the point, `BLOCK_MILES=1.5` + 1.1mi corner-safety pad, `blockBbox`/`milesToDegrees` js:2600-2614), then computes `blockTotals(geojson, latlng)` **client-side** (js:2641-2664): finds the "home" section (the one whose bbox contains the point, nearest by center distance if ambiguous), then sums `lbs_chemical`/`applications` over every section within `BLOCK_METERS = 2414` (≈1.5mi) of the home section's center — mirroring `stats.block_sections`/`block_totals` server-side (comment js:2638, 116-119). A stale-response guard (`open()`, js:2679-2681) drops the result if the popup closed or the filter scope (`commonParams()` serialized) changed while the request was in flight.
- **`titleCaseName(name)`** (js:2705-2716) — only rewrites a name that is *entirely* upper-case (leaves deliberately-mixed-case names like "McKinley" alone); moves a trailing "THE"/"A"/"AN" to the front; preserves known acronyms (`NAME_ACRONYMS`: USD, EOC, YMCA, ..., TK) and any `[A-Z]{1,5}USD` / roman-numeral-looking token, uppercased. Documented as mirroring the server-side `title_case_name` template filter.

### 7.6 Close behaviour recap

No explicit "close all other popups on open" call is needed — Leaflet only shows one popup per map by default — but because `closePopupOnClick: false` is set map-wide, a popup only closes via: its own close button, `map.closePopup()` (called explicitly only in the township zoom-in path when there's no section id, js:2255), a `bindZoomButtons` zoom action tearing down/rebuilding the layer under it, or a layer being removed from the map (grid rebuild, toggle off, adopt swap).

## 8. Markers

### 8.1 Notices (`?notices=`)

- Toggle default: `data-show-notices` (`'0'` = off, else on), overridable by `?notices=0|1`, flipped by the "Notices of intent" checkbox (`onNoticesToggle`, js:666-676).
- Colour: `NOTICE_COLOR = '#d35400'` (js:87) fill, white (`#fff`) 1.5px stroke — same orange used for chemicals-of-concern dots and the SprayDays/tab icon (comment js:85-86).
- Size: `L.circleMarker` `radius: 8` (js:2439), fixed regardless of zoom (no zoom-scaling logic).
- Zoom behaviour: **no minimum zoom gate** — unlike locations, notices load and render at any zoom (subject only to the shared padded-bbox fetch and the endpoint's own cap, which on a 400 clears the layer, js:2412-2420, rather than falling back to anything).
- Pane: `pesticide-notices` (z 450, topmost marker layer).
- Data source/params: see §3.2; re-fetched on `moveend zoomend` (debounced 300ms) unless `covers(loadedNoticeBounds)`.
- Legend row: appended by `appendMarkerLegend()` only while `showNotices` is true — `{color: NOTICE_COLOR, label: 'Notice of intent'}` (js:2047), always listed *after* the location rows (schools/child care) if both are on (js:2046-2047 order).

### 8.2 Locations (`?locations=1`, schools & child care)

- Toggle default: `data-show-locations === '1'`, overridable by `?locations=0|1`, flipped by the "Schools & child care" checkbox (`onLocationsToggle`, js:678-689).
- Colours by type (`LOCATION_COLORS`, js:93-97): `public_school`/`private_school` → `#5a6b7b` (slate); `child_care` → `#1c9099` (teal); `LOCATION_FALLBACK_COLOR = '#5a6b7b'` (js:98) for any unrecognized type. Comment (js:90-92) explains teal over purple: purple is already the Chemicals section's colour and would misread as a chemical marker on this map.
- Size: `L.circleMarker` `radius: 5` (js:2575) — smaller than notices (8), white 1.5px stroke, `fillOpacity: 0.95`.
- Pane: `pesticide-locations` (z 440, just under notices).
- **Zoom behaviour / `LOCATIONS_MIN_ZOOM = 9`** (js:106): below this zoom, `loadLocations()` clears the layer and shows `LOCATIONS_ZOOM_NOTE = 'Zoom in to see schools and child care.'` (js:115) instead of fetching (js:2510-2518) — the note surfaces both in the legend panel's `.section-map-locations-note` element and, redundantly, in the live-region status line so the reader gets *something* even with the legend panel collapsed (`updateLocationsNote`, js:2074-2086).
- **`LOCATIONS_MAX_BBOX_DEGREES = 12`** (js:114): mirrors the locations endpoint's own `MAX_BBOX_DEGREES` cap; if the padded fetch bbox's span (`boundsSpan`, js:1306-1308: max of width/height) exceeds this, the request goes out **unpadded** instead (`fetchBounds(true)`, js:2529) rather than risk a 400. Comment (js:107-113) walks through why zoom 9 stays under the cap either way on any plausible screen.
- County scope carried along (js:2530-2536): the fetch always includes `county` even though locations aren't grid cells, because the bbox necessarily overhangs the county line and a marker just outside it would otherwise show block-total figures scoped to a county the page isn't displaying.
- Legend rows: `MARKER_LEGEND = [{color: LOCATION_COLORS.public_school, label:'School'}, {color: LOCATION_COLORS.child_care, label:'Child care'}]` (js:100-103) — only two rows even though `private_school` shares the school colour (no separate legend entry for it).

## 9. Controls

### 9.1 Zoom

Default Leaflet `zoomControl: true` (js:704), topleft, unmodified. No custom zoom buttons.

### 9.2 Locate

- **`addLocateControl()`** (js:782-803): skipped entirely if `!navigator.geolocation`. A `L.Control` (topleft, stacks under the zoom control) with a `fa-location-crosshairs` icon; click → `self.locate()`.
- **`locate()`** (js:844-855): adds `.is-locating` (pulsing CSS animation) to the button, sets status "Finding your location…", calls `navigator.geolocation.getCurrentPosition` with `{enableHighAccuracy: true, timeout: 10000, maximumAge: 60000}`; on failure, removes the locating class and sets status "Couldn't get your location".
- **`showLocation(latlng)`** (js:857-875): clears locating state/status, draws/replaces a small blue `L.circleMarker` (`radius:6, color:#fff, weight:2, fillColor:#3273dc, fillOpacity:1, interactive:false`) on the `pesticide-notices` pane at the located point, sets `this.pendingLocate = latlng`, and `map.setView(latlng, this.sectionZoom(), {animate})` — always zooms to section level regardless of current zoom.
- **Pending locate resolution** (`resolvePendingLocate`, js:877-893): since the section grid for the new viewport hasn't loaded yet when `setView` returns, the located point is held in `this.pendingLocate` and resolved once `renderGrid` next runs at section level (`renderGrid` calls `resolvePendingLocate()` unconditionally after a section load, js:2145). It bails early if not at section level or no `gridLayer`, or if the point isn't within `map.getBounds()` yet; otherwise finds the containing grid layer via `getBounds().contains(latlng)` and opens its section popup (`showSectionPopup`), clearing `pendingLocate`. If the grid has loaded but nothing contains the point (outside the valley), `pendingLocate` is cleared without selecting anything, so it doesn't linger waiting forever.
- **`drawRadius`**: unrelated to locate — see §9.6/§10; draws the `data-radius` circle around `data-center` at init/adopt time, not around the geolocated point.

### 9.3 Reset / home

- **`addResetControl()`** (js:807-826): `L.Control` (topleft, under Locate), `fa-house` icon, click → `resetView()`.
- **`resetView()`** (js:828-842): if a county filter (`data.county`) matches a feature in `countiesLayer`, `fitBounds` to that county's outline (`padding:[20,20]`). Else if `countiesLayer` exists at all, `fitBounds` to the *whole counties layer* (valley-wide) — note this branch fires even without a `data-fit="valley"` page, since it's just "counties layer as a whole" as the fallback. Else (no counties layer loaded yet) falls back to `map.setView(parseCenter(data.center) || [36.75,-119.80], parseInt(data.zoom,10) || 8)` — i.e. the page's own original center/zoom, not necessarily the valley.

### 9.4 Expand / compress

- **`toggleExpanded()`** / **`setExpanded(on)`** (js:599-653) — see also §1.3 for the CSS classes involved. Key sequencing:
  1. On expand only: remember `scrollBeforeExpand` and `window.scrollTo(0,0)` — because the site navbar isn't `position: fixed`, the expanded map can only sit flush under it while the page is scrolled to the very top.
  2. Toggle `html.section-map-expanded` **before** anything else, because `fitBelowNavbar()` needs the scope bar already pinned (which that class's CSS rule does) to measure its bottom.
  3. Toggle `.is-expanded` on the wrap; call `fitBelowNavbar()` when turning on, or clear the inline `top` styles (wrap + scope bar) when turning off.
  4. On compress only: restore `window.scrollTo(0, scrollBeforeExpand)`.
  5. (Re)bind a `resize` listener that re-runs `fitBelowNavbar()` while expanded, and an `Escape` keydown listener that calls `setExpanded(false)` while expanded (both removed when not expanded, so they don't accumulate across toggles — bound function references are cached on `this.resizeHandler`/`this.escapeHandler` so `removeEventListener` actually matches).
  6. Update the button's `aria-pressed`/`title`/`aria-label`.
  7. `setTimeout(() => map.invalidateSize(), 0)` — Leaflet needs to be told its container resized after the new CSS layout has applied; the subsequent `moveend` naturally refills the wider grid.
- **`fitBelowNavbar()`** (js:578-595): measures `nav.navbar`'s live `getBoundingClientRect().bottom`; if `.explorer-scope-bar` exists, pins its `top` to that value and re-measures *its* bottom instead (since the scope bar rides between the navbar and the map while expanded); sets `wrapEl.style.top = max(0, bottom - 1) + 'px'` — the `-1` deliberately overlaps the wrap's own 1px top border with the navbar/scope-bar's bottom border so nothing shows a sliver of page through the seam (comment js:580-583, 597-598).
- Reduced motion: expand/compress itself doesn't animate (it's a CSS `position:fixed` layout swap), but the scroll-to-top/scroll-restore always happens instantly (`window.scrollTo`, unconditional, not gated by `reducedMotion`) — no smooth-scroll option was used there in the first place.

### 9.5 Scroll-wheel zoom enable/disable

- Map constructed with `scrollWheelZoom: false` (js:704) so the map doesn't hijack page scroll by default.
- **Enable**: `click` on `.section-map` (js:711), or `focus` on it in the capture phase (`true` as third arg, js:712, so it fires even though the container isn't normally focusable/doesn't bubble focus) → `enableScrollZoom()` (js:1092-1094, `map.scrollWheelZoom.enable()`).
- **Disable**: `mouseleave` (js:713) or `blur` in capture phase (js:714) → `disableScrollZoom()` (js:1096-1098).
- Net effect: scroll-zoom is live only while the pointer is over the map (or it has focus) and turns off the instant the pointer leaves or focus moves away — not merely "sticky after first click."

### 9.6 Options dropdown

Lives in the toolbar (`section-map-toolbar.html`/`section-map.html:40-65`), populated/wired in `attachControls()` (js:398-457): metric radios, notices/locations/all-sections checkboxes, tiles/ramp/bins `<select>`s (options generated client-side from `TILE_STYLES`/`RAMPS`/`BIN_OPTIONS`), and the live-region status span. Opening/closing behaviour is generic dropdown handling shared with the filter dropdowns — see §9.7.

### 9.7 Toolbar dropdown open/close (filters + Options)

`bindToolbar(wrap)` (js:474-529), bound once per toolbar element (`data-bound` guard):
- Each `.dropdown-trigger .button` click: `stopPropagation`, toggle that dropdown's `.is-active` (closing all others first via `closeAll(except)`), update `aria-expanded`, and on opening, focus the first `input[type=search], select` inside it (so a picker's search box is immediately typeable).
- Clicks inside a `.dropdown-menu` are stopped from bubbling (so typing/picking doesn't trigger the document-level close-all).
- `document` `click` → close all; `document` `keydown` Escape → close all. (Both listeners are added unconditionally every time `bindToolbar` runs for a *new* toolbar element, but `bindToolbar` itself is guarded by `data-bound` on the toolbar, so this only happens once per distinct toolbar DOM node, not once per adopt.)
- The filter `<form>` (`.section-map-toolbar-filters`) gets an `htmx:configRequest` listener (js:486-492) that injects the map's own view state (`metric`, `notices`, `locations`, `sections`) into the outgoing GET params whenever they differ from the page defaults — so submitting a filter change doesn't silently reset the map's view toggles.

### 9.8 Panel collapse state

- **`bindPanelToggles(wrap)`** (js:552-561): for every `.section-map-panel[data-panel]` (currently just the legend panel, `data-panel="legend"`), applies the stored collapsed state immediately (`setPanelCollapsed`, reading `readPanelState`) and binds its `.section-map-panel-toggle` click (guarded by `data-bound`) to `onPanelToggle`.
- **Storage**: `localStorage`, key `pesticides:section-map:panel:<name>` (`PANEL_STORAGE_PREFIX`, js:534), value `'collapsed'`/`'open'`; both read and write wrapped in `try/catch` (js:536-550) so a throwing/absent `localStorage` (private browsing, blocked storage) degrades to "always open" without breaking the panel.
- **`onPanelToggle(panel)`** (js:563-567) flips the class and persists the new state under that panel's `data-panel` name.
- **`setPanelCollapsed(panel, collapsed)`** (js:569-573) toggles `.is-collapsed` and the toggle button's `aria-expanded`.

## 10. Fitting

### 10.1 `data-fit` values

Only one meaningful value is checked in code: `data.fit === 'valley'` (js:1049). Used solely inside `fitCounty()` to decide whether to zoom back out to the whole counties layer when there's no county filter. Any other/absent value simply skips that branch (the map just keeps whatever view it already has).

### 10.2 `loadCounties()` + `fitCounty()`

- `loadCounties()` (js:1016-1035): fetches `data.countiesUrl` once (no params), builds `countiesLayer` (non-interactive, `pesticide-counties` pane, `countyStyle()`), then calls `fitCounty()`.
- `fitCounty()` (js:1040-1060):
  - If `data.county` matches a feature's `properties.slug` in `countiesLayer` → `fitBounds` to that one county, `padding:[20,20]`, animated per `reducedMotion`.
  - Else if `data.fit === 'valley'` **and** (`this.countyFitted` is true, i.e. we just came from a county-filtered view, **or** `!this.valleyFitted`, i.e. this is the first time) → `fitBounds` to the entire `countiesLayer` bounds (the whole valley). Animation is suppressed on the very first fit (`animate = valleyFitted && !reducedMotion` — `valleyFitted` is only set true *after* this line, so the first call always snaps) so the initial framing doesn't visibly animate out from the placeholder `data-center`/`data-zoom` view; only clearing a county filter later animates.
  - Comment (js:1051-1054) clarifies why this guard matters: a place/section page frames itself via its own `data-center`/`data-zoom` in `adopt()`, and clearing the county filter there must not zoom back out over that page-specific framing — so the valley refit is gated behind actually having a `data-fit="valley"` page.
  - `this.countyFitted = !!target` is updated every call, tracking "did we just fit to a specific county" for the next call's guard.

### 10.3 `loadOutline()` for region pages

`loadOutline()` (js:1064-1086): fetches `data.outlineUrl` (a regions-API JSON envelope), extracts `payload.data.boundary.geometry`, draws it on `pesticide-outline` pane (fixed style, see §3.3), and `fitBounds` to it with `padding:[24,24]`. This is the mechanism for city/ZIP/place pages to frame themselves around a specific boundary rather than a county or the valley. On `adopt()`, if `data-outline-url` changed, the old `outlineLayer` is removed and `loadOutline()` re-runs (js:963-969).

### 10.4 `data-center` / `data-zoom`

Parsed by `parseCenter()` (js:1100-1108, expects `"lat,lng"`, returns `null` on any parse failure) and `parseInt(data.zoom, 10)`, defaulting to `[36.75, -119.80]` / `8` (roughly the SJV valley centroid) whenever missing or unparsable. Used at initial `map.setView` (js:699-700, 725) and, on `adopt()`, only when `viewChanged` (center or zoom attribute differs from before) and `radiusChanged` is false (radius redraw takes priority and does its own `fitBounds`, js:972-976).

### 10.5 Reduced-motion handling

`prefersReducedMotion()` (js:163-169) wraps `window.matchMedia('(prefers-reduced-motion: reduce)').matches` in a try/catch (returns `false` on any failure, e.g. no `matchMedia`), evaluated once per `SectionMap` instance at construction (`this.reducedMotion`, js:337) — **not** re-evaluated live if the OS setting changes mid-session. Every `animate:` option passed to Leaflet (`setView`, `fitBounds`) throughout the file is `!this.reducedMotion` (or `animate && !this.reducedMotion` for the one doubly-gated case in `fitCounty`). Also gates the panel chevron's CSS rotation transition (`@media (prefers-reduced-motion: reduce) { transition: none }`, css:97-101) and the locate-button pulsing animation (css:391-395).

### 10.6 `valleyFitted` / `countyFitted` flags and the fitBounds animate quirk

- `valleyFitted` (undefined until first valley fit, then `true` forever) — see 10.2; exists purely to make the *first* valley-wide fit snap instead of animate (avoiding a visible zoom-out from the placeholder view on page load), while every subsequent valley refit (e.g. clearing a county filter) does animate.
- `countyFitted` (`true`/`false`, updated every `fitCounty()` call) — tracks whether the map is currently fit to a specific county, used only to gate re-fitting the whole valley when the county filter is cleared (so clearing the filter on a *fresh* page load, before any county was ever fit, doesn't spuriously trigger the valley animate-fit logic beyond what `!valleyFitted` already covers — the two conditions are effectively OR'd: `countyFitted || !valleyFitted`).
- Neither flag is reset in `adopt()`, so they persist across htmx swaps for the life of the one `liveMap` instance — meaning "first load" framing behaviour (the animate suppression) only ever happens once per full page load, not once per swap.

## 11. Status/loading messages, error handling, abort of stale requests

### 11.1 `setStatus(message)` (js:1126-1128)

Writes `message || ''` to `this.statusEl` (`.section-map-status`, a `<span aria-live="polite">` inside the Options dropdown, `section-map.html:62`) if it exists. This is the map's one live-region announcement channel — everything below funnels through it.

### 11.2 Messages by source

- `"Loading sections…"` — `loadSections()` start (js:1335).
- `"Loading grid…"` — `loadTownships()` start (js:1397).
- `"Loading sections… 0 of N"` → `"…N of M"` progressing → `""` on completion — `loadAllSections()` (js:1793) and its per-block callback (js:1777).
- `"Couldn't load sections; try again"` — sections fetch failed non-200 (non-400) or threw (js:1363, 1377).
- `"Couldn't load the grid; try again"` — townships fetch threw (js:1428).
- `""` — cleared on any successful sections/townships load (js:1366, 1414) and when all-sections finishes.
- `"Finding your location…"` → `""` / `"Couldn't get your location"` — geolocation flow (js:847, 853, 859).
- `LOCATIONS_ZOOM_NOTE` ("Zoom in to see schools and child care.") — set/cleared by `updateLocationsNote()` (js:2074-2086) whenever the locations toggle is on but the map is zoomed out past `LOCATIONS_MIN_ZOOM`; careful not to stomp a load-in-progress message — it only clears the status line if the status line currently holds exactly that note (js:2083).

### 11.3 Error handling patterns

- Every `fetch(...)` chain follows the same shape: `.then(checkOk/parse json).then(handle).catch(handle error)`, with `AbortError` explicitly ignored first in every catch (`if (err && err.name === 'AbortError') return;`) so a deliberately superseded request never shows an error.
- After the abort check, each catch also re-checks that its own abort-controller reference is still current (`if (self.gridAbort !== abort) return;` etc.) — belt-and-braces against a slow non-abort-aware environment or a response that resolves after a newer request already started.
- Sections: 400 response triggers the padded→unpadded→township fallback chain (§4) rather than an error message; any other non-ok status or a thrown error clears the grid, resets `loadedBounds`/`loadedLevel`, clears the legend, and sets the "try again" status (js:1346-1378).
- Townships: non-ok throws generically (`throw new Error('bad response')`, js:1402); catch clears the grid the same way (js:1420-1429). No 400-specific fallback for townships (there's nowhere further out to fall back to).
- Notices: non-ok throws; catch clears `loadedNoticeBounds` and the notices layer (js:2412-2420) — no status message shown for this failure, only a `console.error`. Comment (js:2415-2416) notes a very wide zoomed-out bbox can 400 past the endpoint's cap; the result is just "no notices," silently.
- Locations: same pattern — clears `loadedLocationBounds` and the layer, `console.error` only, no status message (js:2550-2556).
- Section-detail (`showSectionPopup`) and location-block (`loadLocationBlock`) fetch failures degrade the popup's *content* to a "Couldn't load…" note rather than touching the status line, and both guard against writing into a popup that's since closed (js:2355,2370 / js:2689,2694).
- All `console.error` calls are guarded (`window.console && console.error && console.error(...)`) for environments without a console.

### 11.4 Abort of stale requests

- **Grid**: `startGridRequest()` (js:1318-1323) — a single `AbortController` shared by sections and townships; calling it again aborts whatever was previously in flight (whether section or township), because deciding to load one level makes a pending request for the other stale by definition.
- **Notices**: its own `AbortController` (`this.noticesAbort`), aborted and replaced at the top of `loadNotices()` (js:2382-2384) and explicitly aborted when the toggle is turned off (`onNoticesToggle`, js:673) or a page swap changes the notices default off (`adopt()`, js:939).
- **Locations**: same pattern with `this.locationsAbort` (js:2524-2526, 685, 949).
- Lens/all-sections fetches (`fetchLensSections`) are **not** abortable — they're cheap per-township-block requests and simply write into whatever `lensCache` object was current when they started (see §5.2); a superseded fetch's result is either harmless (still-relevant cache) or silently discarded (cache object replaced wholesale in `adopt()`).
- `AbortController` itself is feature-detected (`typeof AbortController !== 'undefined'`) everywhere it's used, so the abort mechanism degrades to "just check the reference" on very old browsers rather than throwing.

## 12. The htmx lifecycle

### 12.1 How the map gets (re-)initialised

`assets/js/pesticides/explorer.js` wires `#explorer` (`hx-boost`, per file header comment js:1-15) so links/GET forms swap `#explorer`'s content and push the URL, but every page is still a full server render on plain GET. Key settings:
- `htmx.config.historyCacheSize = 0` (explorer.js:25) — Leaflet mutates its container's DOM, so a cached back/forward history snapshot would contain dead map markup with `data-rendered` already set, which `init()` would then skip; forcing a real refetch avoids that.
- `htmx.config.scrollBehavior = 'instant'`, `scrollIntoViewOnBoost = false` (explorer.js:26,30) — a same-page filter/sort/year change shouldn't scroll the reader; only a navigation to a genuinely different page scrolls to top (handled manually in `afterSwap`, explorer.js:122-126, comparing `window.location.pathname` before/after).
- **`htmx:load`** (explorer.js:34-44) fires once on initial page load and again for every swapped-in element; it calls, in order: `PesticidesCharts.init`, `PesticidesSectionMapGL.init` (the GL spike, if loaded), `PesticidesSectionMap.init` (the Leaflet script, this file), `PesticidesFindArea.init`, `PesticidesEntityPicker.init`, `SJVAirLeafletMaps.init` — all guarded by `typeof window.X !== 'undefined'` checks, so pages without the map script loaded are unaffected. The GL script's init runs **before** the Leaflet script's init on every swap.

### 12.2 `init(root)` discovery (js:2785-2808)

- Bails immediately if `typeof L === 'undefined'` (Leaflet not loaded on this page at all).
- `containersUnder(root || document)` (js:2771-2777) — matches `root` itself if it's a `.section-map`, plus every `.section-map` under it (handles htmx handing over either the swapped element directly or an ancestor).
- Skips any container with `dataset.rendered` truthy (already live) **or** `dataset.gl` truthy (§1.1 — explicitly ceded to the GL spike) — `el.dataset.rendered || el.dataset.gl` (js:2796).
- For each remaining container: if there's an existing `liveMap` whose element is no longer attached to `document.body` (i.e. the old container was swapped out of the DOM), calls `liveMap.adopt(el)` — reusing the one Leaflet instance rather than tearing it down and rebuilding (comment js:2781-2782, 909-913: avoids the grey flash of retiling). Otherwise marks the new container `data-rendered='1'` and constructs a fresh `new SectionMap(el)`, replacing `liveMap`.
- Errors constructing/adopting are caught and logged, not rethrown (js:2797-2806) — a broken map doesn't take the rest of `htmx:load`'s initializers down with it.
- Special case (js:2790-2793): if the previous `liveMap` was expanded and its element is no longer in the DOM **and** there are no `.section-map` containers at all on the new page, `liveMap.setExpanded(false)` is called explicitly — otherwise the page-level expanded-mode side effects (`html.section-map-expanded` class, pinned scope bar) would be stuck on with no map left to ever turn them off.
- `window.PesticidesSectionMap = { init: init }` (js:2810) is the only global export; `initDocument()` (js:2812-2814) calls `init(document)` once on `DOMContentLoaded` (or immediately if already past `loading` readyState) for the very first page load, independent of htmx.

### 12.3 `data-rendered`

Set to `'1'` by `init()` right before constructing a new `SectionMap` (js:2802) and again inside `adopt()` (js:926, redundant but explicit) after an existing map takes over a new container. It is explicitly preserved across an `adopt()`'s attribute sync — the loop that copies/deletes dataset keys special-cases it (`key !== 'rendered'`, js:923) so a stale container's other attributes can be wiped without also erasing the render flag mid-adopt.

### 12.4 `adopt(newEl)` — what carries across a swap (js:914-1002)

Full detail already covered in §5/§9/§10 where relevant; consolidated here:
- **DOM swap**: `newEl.parentNode.replaceChild(this.el, newEl)` — the *old*, live `.section-map` element (with its Leaflet canvas/SVG already attached) physically replaces the freshly-rendered-but-inert one the server sent; then every `data-*` attribute is synced from `newEl` onto `this.el` (removing keys that no longer exist, preserving `rendered`; js:915-926), and `this.el.id` is updated to the new id (`section-map-{year}` changes when the year filter changes).
- **Carries across unconditionally**: the Leaflet `map` instance itself (all panes, base tile layer, zoom/locate/reset controls, `countiesLayer` — never reloaded unless outline/view logic below triggers it), `selectedSectionId`/`openGridId`/etc. popup-tracking state (not explicitly cleared, so a still-matching feature reopens via `reopenSelectedSection`/`reopenGridPopup` — see §7.3.1), `valleyFitted`/`countyFitted` flags (§10.6), scroll/expanded state.
- **Reset when `dataChanged`** (any of `year, chemical, product, commodity, county, concern` differs, `DATA_KEYS` js:907): `loadedBounds = null`, `loadedNoticeBounds = null`, **`lensCache = {}`** (fresh object — any in-flight fetch from the old cache lands in the discarded object, see §5.2), `allSectionsRun = null` (stops any in-flight all-sections run from scheduling further work), then reloads grid/notices; `loadedLocationBounds = null` + reload locations too (comment js:990-991: the markers don't change with filters, but their popups' block totals do, so the layer is rebuilt anyway).
- **Notices/locations *default* changes independently of `dataChanged`** (`data-show-notices`/`data-show-locations` differ from before, e.g. navigating from a chemical page to a school-district page): re-derives `this.showNotices`/`this.showLocations` from the new default, aborts+clears the layer if the new default is off, or reloads it if `dataChanged` didn't already and the new default is on (js:929-952, 995-996).
- **View/outline/radius**: `outlineChanged` → drop old `outlineLayer`, `loadOutline()` again; `radiusChanged` → `drawRadius(center)` (takes priority over a plain view change since it does its own `fitBounds`); else `viewChanged` (center or zoom attribute differs) → `map.setView(...)`; `countyChanged` → `fitCounty()`.
- **Unchanged data** (`!dataChanged`) still gets `updateLegend()` + `restyle()` (js:998-999) — comment: "Same data; the legend/level notes are new elements and need filling" — i.e. even with no data change, the legend/status/level DOM nodes are freshly re-queried by `attachControls()` and need their content set again since they're new elements in the swapped DOM.
- `attachControls()` and `map.invalidateSize()` are called unconditionally at the top of `adopt()` (js:954-955) — every swap re-finds toolbar/panel/legend elements and re-binds their listeners (idempotently, via `data-bound` guards) since they're fresh DOM nodes even when the map instance itself persists.

### 12.5 Expanded state cleared on swap

Not handled inside `adopt()` itself — `setExpanded`/the `.is-expanded`/`.section-map-expanded` classes are left alone across an ordinary adopt (expanding is a per-map-instance, not per-page, concept, and the wrap element travels with the live map via `replaceChild`). The only explicit clear-on-swap path is the one in `init()` covered in §12.2: when the *entire* map disappears from the new page (no `.section-map` containers left) while the previous instance was expanded, `setExpanded(false)` is called to undo the document-level side effects that would otherwise have nothing left to reset them.

## 13. Every constant, with its value

Module-level (top of `section-map.js`) unless noted:

| constant | value | line | notes |
|---|---|---|---|
| `SECTION_ZOOM` | `11` | js:21 | floor zoom for sections vs townships |
| `MAX_VIEWPORT_SECTIONS` | `2000` | js:24 | viewport section-count budget for `sectionZoom()` |
| `METERS_PER_MILE` | `1609.34` | js:25 | |
| `TOWNSHIP_DEGREES` | `{lat: 0.087, lng: 0.108}` | js:27 | one township's degree span near 36°N |
| `DEBOUNCE_MS` | `300` | js:28 | grid/notices/locations reload debounce on `moveend zoomend` |
| `LENS_FETCH_DELAY_MS` | `50` | js:31 | hover-rest delay before an uncached lens fetch |
| `ALL_SECTIONS_CONCURRENCY` | `4` | js:33 | concurrent block fetches in "all sections" mode |
| `ALL_SECTIONS_REDRAW_MS` | `600` | js:35 | throttle for reclassing while all-sections blocks land |
| `RAMPS` | 12 named 5-stop hex arrays | js:37-53 | `blues` (default), `purd`, `bupu`, `ylorbr`, `putrid`, `bile`, `putrid2`, `ylgnbu`, `pubugn`, `mako`, `cividis` — see §6.3 for full hex values |
| `RAMP` | `RAMPS[?ramp=] \|\| RAMPS.blues` | js:54-55 | mutable, reassigned by `onRampChange` |
| `NO_DATA_COLOR` | `#f0f0f0` | js:56 | |
| `BIN_OPTIONS` | `[[4,'Quartiles'],[5,'Quintiles'],[6,'Sextiles'],[8,'Octiles'],[10,'Deciles']]` | js:58 | |
| `DEFAULT_BINS` | `6` | js:60 | |
| `NUM_CLASSES` | `?bins= \|\| DEFAULT_BINS` | js:59-61 | mutable, reassigned by `onBinsChange` |
| `TILE_STYLES` | `['streets','basic-v2','bright-v2','dataviz','dataviz-light','topo-v2','outdoor-v2','toner-v2','hybrid']` | js:80 | |
| `NOTICE_COLOR` | `#d35400` | js:87 | |
| `LOCATION_COLORS` | `{public_school:'#5a6b7b', private_school:'#5a6b7b', child_care:'#1c9099'}` | js:93-97 | |
| `LOCATION_FALLBACK_COLOR` | `#5a6b7b` | js:98 | |
| `MARKER_LEGEND` | `[{color:'#5a6b7b',label:'School'},{color:'#1c9099',label:'Child care'}]` | js:100-103 | |
| `LOCATIONS_MIN_ZOOM` | `9` | js:106 | |
| `LOCATIONS_MAX_BBOX_DEGREES` | `12` | js:114 | |
| `LOCATIONS_ZOOM_NOTE` | `'Zoom in to see schools and child care.'` | js:115 | |
| `BLOCK_MILES` | `1.5` | js:119 | |
| `BLOCK_METERS` | `2414` | js:120 | ≈1.5 miles |
| `SECTION_LINES_MIN_ZOOM` | `10` | js:124 | |
| `SPRAYDAYS_URL` | `'https://spraydays.cdpr.ca.gov/'` | js:125 | |
| `METRIC_UNITS` | `{lbs_chemical:'lbs', applications:'applications'}` | js:127-130 | |
| `METRIC_LABELS` | `{lbs_chemical:'Pounds applied', applications:'Applications'}` | js:132-135 | defined but not referenced elsewhere in the file (dead/unused — metric radio labels are hardcoded in the HTML template instead, `section-map.html:51-52`) |
| `BBOX_PAD` | `0.5` | js:141 | half a viewport, each side |
| `POPUP_OPTIONS` | `{maxWidth:320, autoPanPadding:[24,24], closeButton:true}` | js:145-149 | |
| `LEVEL_TEXT` | 3 strings (section/township/allSections) | js:151-155 | see §6.4 |
| `COUNTY_COLOR` | `#1f2d3d` | js:157 | |
| `GRID_LINE` | `{color:'#1f2d3d', opacity:0.18}` | js:159 | |
| `SELECTED_LINE` | `{stroke:true, color:'#1f2d3d', opacity:0.9, weight:1.5}` | js:161 | |
| `PANEL_STORAGE_PREFIX` | `'pesticides:section-map:panel:'` | js:534 | |
| `NAME_ACRONYMS` | `{USD,EOC,YMCA,YWCA,CDC,CDCC,CCC,LLC,INC,KCAO,CSU,CSUF,UC,UCSF,SJV,CA,PS,HS,JHS,MS,ES,MLK,JFK,ABC,HSA,ROP,STEM,STEAM,TK}` | js:2704 | for `titleCaseName` |
| `DATA_KEYS` | `['year','chemical','product','commodity','county','concern']` | js:907 | which `data-*` changes count as a data change in `adopt()` |

Fixed magic numbers inline (not named constants):
- Hover stroke weights: `2.5` (township) / `2` (section) — `hoverStyle`, js:1499; lens hover weight `2` — `lensHoverStyle`, js:1505.
- Grid stroke weights: `0.75` (township) / `0.5` (section) — `featureStyle`, js:1481; lens/all-sections weight `0.5` (`lensSectionStyle`, js:1932), bumped to `1` below `SECTION_LINES_MIN_ZOOM` for the hairline-seam fix (js:1946).
- Fill opacities: `0.7`/`0.25` (grid, with/without data, js:1477), `0.85`/`0.35` (lens/all-sections, with/without data, js:1925).
- Notice marker: `radius:8`, `weight:1.5` (js:2437-2444). Location marker: `radius:5`, `weight:1.5`, `fillOpacity:0.95` (js:2573-2580). Locate-me dot: `radius:6`, `weight:2` (js:861-869).
- Lens clear grace period: `120` ms (js:2012). Idle-prefetch timeout: `500` ms (`requestIdleCallback`) / `150` ms `setTimeout` fallback (js:1669,1671).
- Geolocation options: `enableHighAccuracy:true, timeout:10000, maximumAge:60000` (js:854).
- `blockBbox` corner-safety pad: `BLOCK_MILES + 1.1` miles (js:2612).
- Default center/zoom fallback: `[36.75, -119.80]`, zoom `8` (js:699-700, 725, 840, 971).
- `fitCounty`/`fitBounds`/`loadOutline` paddings: `[20,20]` (county/valley), `[24,24]` (region outline).

## 14. Accessibility (aria, keyboard, focus)

- **Live region**: `.section-map-status` carries `aria-live="polite"` (`section-map.html:62`), the sole channel for status/loading/error/geolocation/zoom-note announcements (§11).
- **Toolbar dropdown triggers**: `aria-haspopup="true"`, `aria-expanded` kept in sync with `.is-active` on open/close (js:500,513, explorer's own scope-bar pickers do the same in `explorer.js:56,60`).
- **Panel toggle**: `aria-expanded` on `.section-map-panel-toggle` mirrors collapsed state (js:572, initial markup `section-map.html:75` `aria-expanded="true"`), `aria-controls="section-map-legend-{year}"` points at the panel body id (`section-map.html:75,81`).
- **Expand button**: `aria-pressed` reflects expanded state; `title`/`aria-label` swap between "Expand the map" / "Back to the page" (js:638-642); icon spans are `aria-hidden="true"` (`section-map.html:68-69`) since the button already has a text label via `aria-label`/`title`.
- **Locate/Reset controls**: each anchor has `role="button"`, `title`, and `aria-label` (js:791-793, 815-817); icon span `aria-hidden="true"`.
- **Icons throughout** (fontawesome spans in popups, legend, toolbar) are `aria-hidden="true"` where decorative (e.g. `section-map.html:43,45,68-69,76,78`; popup action icons in `sectionPopupHtml`/`noticePopupHtml`/`locationPopupHtml` are plain `<span class="fa-regular ...">` with no `aria-hidden`, since they sit inside a link/button whose text already labels the action — an inconsistency worth flagging for the port, see §15/summary).
- **Keyboard**: Escape closes all open toolbar/Options dropdowns (`bindToolbar`'s document keydown, js:526-528) and, separately, exits expanded mode (`escapeHandler`, js:643-649) — both bound at the document level so they work regardless of focus location. Opening a dropdown moves focus into it (`focusable.focus()` onto the first `input[type=search], select`, js:515-517). No explicit focus trap while expanded or while a dropdown is open; no explicit roving-tabindex/arrow-key handling for the metric radios or grid cells (native radio/click semantics only).
- **Grid cells / markers**: rendered as SVG/canvas paths via Leaflet with no `role`/`tabindex`/keyboard equivalents — hover and click are mouse-only; there is no keyboard way to open a section/notice/location popup or trigger the lens. This is a pre-existing gap in the Leaflet implementation, not something the port needs to preserve deliberately, but worth naming since a GL rewrite is a natural point to fix it.
- **`prefers-reduced-motion`**: honored for map pan/zoom animation (`reducedMotion`, §10.5) and for the panel chevron transition / locate pulse animation (CSS `@media` blocks, css:97-101, 391-395) — not merely a courtesy note, an actual behavioural difference.
- **Focus restoration on htmx swap**: not part of the map itself, but `explorer.js`'s `htmx:afterSwap` handler (explorer.js:122-137) refocuses a search input (by id) that had focus before the request, including entity-picker search boxes inside the map's own toolbar dropdowns.
- **`noscript` fallback**: `section-map.html:87` renders a static `county-map.html` include when JS is unavailable — the entire interactive map (and everything in this inventory) has zero accessible/functional equivalent without JS beyond that static fallback.

## 15. What the spike (`section-map-gl.js`) already implements, and what it doesn't

Loaded only under `?gl=1` (`camp/templates/pesticides/base.html:19-24`, injecting the MapTiler SDK CDN assets and the script itself); explicitly labeled "SPIKE — throwaway" (gl.js:1-9). Its own `init()` (gl.js:345-359) only claims containers with `data-gl` truthy (`section-map.html:30` sets `data-gl` from `request.GET.gl`), which is exactly the set the Leaflet `init()` skips (js:2796) — the two scripts never both attach to the same container. Both `<script>` tags load unconditionally (Leaflet init runs even under `?gl=1`; it just no-ops on the `data-gl` container), and `explorer.js`'s `htmx:load` handler calls the GL init before the Leaflet init on every swap (§12.1).

### 15.1 Implemented (rough parity)

- **Grid**: fetches sections or townships from the same endpoints with the same `commonParams()` shape, at a fixed `SECTION_ZOOM = 11` threshold (gl.js:15,181) — no viewport-based `sectionZoom()`/`MAX_VIEWPORT_SECTIONS` adjustment (see gap below).
- **Quantile classing**: `quantileClasses`/`sampleRamp`/`colorFor` are near-identical ports (gl.js:28-58) — fixed at `NUM_CLASSES = 6` and the `blues` ramp only, no live ramp/bins switching.
- **Fill/line styling**: done as MapLibre paint expressions on GeoJSON sources (`grid`, `lens`, `lens-outline`) using per-feature `fill`/`opacity` properties computed in JS and a `feature-state` `hover` boolean via `promoteId: 'id'` (gl.js:136,212-217) — the GL-idiomatic hover mechanism, a real architectural difference worth carrying into the real port (avoids per-feature event rebinding on every style pass).
- **Township hover → lens at 50ms delay**: same threshold and 3x3 neighborhood-by-center-distance approach (`neighbourhood`, gl.js:241-253, reach hardcoded `1.5`), with its own per-neighborhood-key cache (`lensCache[ids.sort().join('|')]`, gl.js:275-276) — a materially different cache granularity from production's per-township-id cache (§5.2), so a redraw one township over always refetches rather than reusing 8 of 9 cached townships.
- **Basic click popup**: a MapTiler `Popup` with a subset of section/township content (name, metric line, and — township only — a "Zoom in to sections" button that `easeTo`s to `SECTION_ZOOM` at the clicked point) — no top-chemicals fetch, no action links, no notice/location popups.
- **`data-fit="valley"` handling**: fits to a hardcoded `VALLEY` bbox constant (gl.js:21) rather than the counties GeoJSON's actual bounds.
- **Perf instrumentation**: `window.__glStats`, console-logged style-load/first-idle/grid-fetch timings, and a MapTiler request/query-key/session-id report (`reportRequests`, gl.js:322-338) scraped from the Performance API — purely a comparison tool for judging the port, not a feature to carry over.

### 15.2 Not implemented at all (full gaps against §1-14 above)

- **No county outlines, no region outline (`loadOutline`), no radius circle, no notices layer, no locations layer** — none of §3's non-grid layers exist; nothing from §8 (markers) exists.
- **No "All sections" mode** — none of §5.6 (`showAllSections`, canvas/5x5-block loading, `scheduleAllSectionsDraw`) exists.
- **No lens prefetch ring, no lens outline on the real township polygon** (draws a bbox rectangle instead, `bboxPolygon(union)`, gl.js:73-75,273, not the township's actual geometry), **no lens-clear grace period distinct from a flat 150ms timeout**, no `openLensId`-pinning-on-open-popup interaction (there's no lens-section popup at all to pin against).
- **No selected-section outline/persistence** (`selectSection`/`reopenSelectedSection`/`isSelected`, §7.3.1) — clicking a section just opens a transient popup with no lasting visual state.
- **No `sectionZoom()` viewport adjustment / `MAX_VIEWPORT_SECTIONS` cap** — fixed `SECTION_ZOOM=11` regardless of viewport size or aspect, so a very wide (e.g. expanded) map could ask for more sections than the endpoint allows with no fallback (no 400→unpadded→township chain either, gl.js:188-209 just treats a non-ok response as "no data").
- **No `covers()`/`loadedBounds` skip-refetch logic** — `loadGrid` runs on every `moveend` unconditionally (with only a padding of `0.2` vs. production's `BBOX_PAD=0.5`, gl.js:185), and there's no debounce at all on the `moveend` listener (§4's `DEBOUNCE_MS=300` has no counterpart) — likely to fire far more requests during a drag/zoom sequence.
- **No `geometry=0` values-only township refetch** (§4) — every township fetch is a full fetch.
- **No `SECTION_LINES_MIN_ZOOM` hairline-seam handling** — not applicable in the same way since MapLibre vector rendering doesn't have Leaflet-canvas's antialiasing-seam problem, but also no equivalent no-data-invisible-below-a-threshold behaviour.
- **No URL query param sync** — `?metric=`, `?notices=`, `?locations=`, `?sections=`, `?tiles=`, `?ramp=`, `?bins=` are entirely absent; metric is hardcoded to `lbs_chemical`, nothing is read from or written to `window.location`.
- **No controls beyond the built-in `navigationControl`** — no locate control/geolocation flow, no reset/home control, no expand/compress, no Options dropdown, no scroll-wheel enable-on-focus/click behaviour (`scrollZoom: false` is simply permanent), no panel collapse/legend panel at all (no legend is rendered anywhere in the spike).
- **No status/loading/error UI** — no live region, no "Loading sections…" / "Couldn't load…" messages; failures are `console.error` only, and there's no abort-controller-based stale-request cancellation (a superseded fetch is only guarded by a simple request-counter check, `request !== self.stats.requests`, gl.js:191, for the grid only — lens/click fetches have no staleness guard at all).
- **No real htmx `adopt()`** — `init()` just destroys any instance whose element left the DOM and constructs a brand-new `GLMap` for any new `data-gl` container (gl.js:345-359); there is no in-place reuse of the map/view/cache across a filter or year swap, so every htmx swap on a `?gl=1` page fully re-creates the MapLibre map (new tile requests, lost lens cache, reset view) — a materially different (and more expensive) swap story than Leaflet's `adopt()` (§12.4).
- **No accessibility work** — no aria-live status, no keyboard handling beyond MapLibre's own defaults, no `prefers-reduced-motion` handling (`animate: false` is hardcoded only for the valley fit, gl.js:111).
- **No `data-highlight` (page's own section outline), no `data-radius`, no `data-outline-url`, no `data-show-notices`/`data-show-locations` handling** — these `data-*` attributes are present on the shared container markup but simply never read by `gl.js`.

## 16. Appendix: server-side `data-*` contract and GeoJSON endpoints

Supporting detail for §1–§11, from `section_map_config()` (`camp/apps/pesticides/views.py:1010-1059`), its call sites, and the endpoint modules.

### 16.1 `section_map_config(year, *, center, zoom, radius, chemical, product, commodity, county, highlight, outline_url, all_years, show_notices=True, show_locations=False, concern=False)`

- URLs are **hardcoded string literals**, not `reverse()`'d: `sections_url='/api/2.0/pesticides/sections/'`, `counties_url='/api/2.0/pesticides/counties/'`, `townships_url='/api/2.0/pesticides/townships/'`, `notices_url='/api/2.0/pesticides/notices/active/'`, `locations_url='/api/2.0/pesticides/locations/'`, `section_url_pattern='/api/2.0/pesticides/sections/{id}/'` (views.py:1020-1025) — confirmed to match `camp/api/v2/pesticides/urls.py:8-11,26` exactly, but a URLconf change would require updating this function by hand (fragile coupling, worth flagging for the port).
- `tile_url`: `leaflet.TILE_URL.format(key=settings.MAPTILER_API_KEY, z='{z}', x='{x}', y='{y}')` (views.py:1035) — a Leaflet-style `{z}/{x}/{y}` template baked with the MapTiler key already in it; §1's `tileUrlFor()` string-replaces the style segment in this same URL for the `?tiles=` experiment control.
- `fit`: `'' if any((center, zoom, radius, highlight, outline_url)) else 'valley'` (views.py:1047) — i.e. `'valley'` fit only applies when the page has **no** explicit framing of its own; any of those five kwargs being truthy suppresses it.
- `year`: `stats.ALL_YEARS if all_years else (year or '')` (views.py:1039) — confirms `data-year` is the literal string `"all"` for the all-years view, matching `yearPhrase()`'s check for `this.data.year === 'all'` (js:2191) — the value is `stats.ALL_YEARS`, not a hardcoded `'all'` string in the JS; worth double-checking that constant's value stays `"all"` across a port.
- `chemical`/`product`/`commodity` are re-encoded as `chem_code`/`prodno`/`site_code` (views.py:1049-1051), not sqids — these are the values the grid/notices endpoints filter on (`apply_filters`, sections.py:62-80), distinct from the sqid-based page-link params (`chemical_page_url` etc. take sqids).
- `center`/`zoom` default to `SJV_CENTER`/`SJV_ZOOM` module constants (views.py:1041-1042) when not passed — not the JS's own hardcoded `[36.75,-119.80]`/`8` fallback (§10.4); the two fallbacks happen to need to agree but live in two different files (another cross-file fragility to watch in the port).

### 16.2 Per-page `map_config` kwargs (each call site)

| view | show_notices | show_locations | center/zoom/radius | highlight | outline_url | notes |
|---|---|---|---|---|---|---|
| `MapPage` (views.py:1081-1089) | default `True` | default `False` | none | none | none | the main explorer map; `fit` ends up `'valley'` |
| Records browser (`get_map_config`, views.py:1450-1473) | `False` (explicit) | default `False` | `resolve_map_center(section, region, point, radius, county)` (views.py:1457-1459, priority: section > region > point+radius > county) | none | none | |
| `NoticeList.get_map_config` (views.py:1740-1759) | default `True` | default `False` | same `resolve_map_center` | none | none | |
| `NoticeDetail` (views.py:1798-1808) | default `True` | default `False` | notice's own point, or its section's centroid, zoom 13 if a center was found | none | none | |
| Section detail (views.py:1606-1611) | default `True` | default `False` | section centroid + zoom 13 if it has a boundary | `section.sqid` | none | the only view that sets `highlight` |
| Place/region pages (`places.py:598-600`, via `area.map_kwargs()`, places.py:147-164) | default `True` | `is_district` (True only for a `Region.Type.SCHOOL_DISTRICT`) | point areas: center+zoom 12+radius; county regions: centroid+zoom 9+`county=slug`; other regions (city/ZIP/place): centroid+zoom 11+`outline_url=/api/2.0/regions/{sqid}/` | none | set for non-county regions | the only view that sets `outline_url`, and the only place `show_locations=True` is ever passed |

- **`resolve_map_center()`** (views.py:244-255) priority order: explicit `section` (zoom 13) → `region` (zoom 10) → `point+radius` (zoom 12) → `county` (zoom 9) → `(None, None, None)` (no framing, so `fit` falls through to `'valley'` if nothing else is set either).
- `centroid(region)` (views.py:238-241) formats `f'{point.y:.4f},{point.x:.4f}'` — 4 decimal places, `"lat,lng"` order, matching `parseCenter()`'s expected format (js:1100-1108).

### 16.3 GeoJSON endpoint contracts (`camp/api/v2/pesticides/`)

**`sections.py` `SectionList`** (`GET /api/2.0/pesticides/sections/`):
- Requires either `bbox=west,south,east,north` or `lat`+`lng` (+ optional `radius`, one of `places.RADIUS_CHOICES`, default `1`).
- Filters: `year` (default latest via `stats.resolve_year_param`), `month` (1-12), `chemical` (chem_code int), `product` (prodno int), `commodity` (site_code), `county` (slug), `concern=1`.
- **`MAX_SECTIONS = 2500`** (sections.py:24) — over that, `400` with `'bbox too large; zoom in'` (bbox request) or `'radius too large'` (radius request) — this is the cap `MAX_VIEWPORT_SECTIONS=2000` in the JS (§4) is deliberately kept under.
- Response: `{type:'FeatureCollection', year, features:[{type:'Feature', id: sqid, geometry, properties:{id, mtrs (external_id, e.g. the MTRS string the JS parses for `lensCache` keys), county, lbs_chemical, lbs_product, acres_treated, applications}}]}`. Note `lbs_product` and `acres_treated` are present in every section feature's properties even though the JS's `METRIC_UNITS`/toggle only ever reads `lbs_chemical`/`applications` (§13) — `lbs_product`/`acres_treated` are unused by the map script today.
- `SectionDetail` (`GET /api/2.0/pesticides/sections/{sqid}/`) — the `data-section-url-pattern` target: returns `{id, mtrs, county, year, geometry, years:[...], months:[...], top_chemicals, top_products, top_commodities}`; the map only reads `top_chemicals` (§7.3), each `{id, name, display_name, lbs}` — no `is_of_concern` field is actually returned by this endpoint despite the JS reading `c.is_of_concern` at js:2361 (**`top()` in `SectionDetailBase.get`, views.py:263-267, does not include `is_of_concern` in the dict it builds** — this looks like a genuine bug/gap: the "chemical of concern" orange dot the JS renders for top chemicals in a section popup, `sectionPopupHtml`'s `chemicals.slice(0,3)` loop, can never actually show since `c.is_of_concern` is always `undefined` there, unlike the notices endpoint which does include it, sections.py — see 16.3's `ActiveNoticeList` row below).
- `TownshipList` (`GET /api/2.0/pesticides/townships/`) — `bbox` optional (whole grid returned unfiltered, "no cap: only a few hundred townships", views.py comment/sections.py:405-406); `geometry=0` returns `geometry: null` for values-only refetch (§4); same filter set as sections; a `county` filter keeps townships whose **center** falls in the county boundary **or** that have nonzero `applications` (a border township with recorded use in that county is kept even if its centroid falls just outside, sections.py:412-415). Response feature properties: `{id, name, sections (count), lbs_chemical, lbs_product, acres_treated, applications}` — `id`/`name` are both the same MTR string (no separate sqid — townships aren't `Region` rows).
- `CountyList` (`GET /api/2.0/pesticides/counties/`) — no params; `{type:'FeatureCollection', features:[{id:sqid, geometry, properties:{id, name, slug}}]}`, sorted by name, cached 24h.
- `ActiveNoticeList` (`GET /api/2.0/pesticides/notices/active/`) — `bbox` optional, plus `chemical`/`product`/`county`. **`MAX_NOTICES = 2000`** (sections.py:25) → 400 `'bbox too large; zoom in'` over that (counted before serializing, sections.py:316-322). Response: `{type:'FeatureCollection', as_of, features:[{id, geometry (point or null), properties:{id, scheduled_application (ISO), scheduled_end (ISO, = scheduled_application + NOTICE_GRACE_DAYS), county, application_method, treated_amount, treated_units, section (MTR string), section_id (sqid), products:[{id,name}], chemicals:[{id,name,display_name,is_of_concern}]}}]}` — chemicals here *do* carry `is_of_concern` (sections.py:340), unlike the section-detail endpoint's `top_chemicals` (see the gap noted above).

**`locations.py` `LocationList`** (`GET /api/2.0/pesticides/locations/`):
- `bbox` **required** (400 `'bbox is required'` without it, locations.py:60-61); **`MAX_BBOX_DEGREES = 12.0`** (locations.py:24) — the actual code cap the JS's `LOCATIONS_MAX_BBOX_DEGREES=12` mirrors. **The class docstring (locations.py:119, "may span at most 3 degrees on a side") is stale/wrong relative to the actual `MAX_BBOX_DEGREES = 12.0` constant it's supposed to describe** — a real drift between comment and code worth flagging in the port so the wrong number doesn't get carried forward.
- Optional `type` (comma-separated subset of `public_school`, `private_school`, `child_care`; 400 if any value is unrecognized) and `county` (slug).
- Response: `{type:'FeatureCollection', features:[{id, geometry, properties:{id, name, type, type_label, address, city, school_district, school_district_id, school_district_url, grade_span, enrollment, capacity}}]}`. The JS's `locationPopupHtml` reads `type_label`, `address`, `city`, `school_district`, `school_district_url`, `name`, `type` — `grade_span`, `enrollment`, `capacity`, `school_district_id` are fetched but currently **unused** by the map popup (no code path reads them; potential content the port could surface, or dead payload to trim).
- `cache_key_version = 2` (locations.py:127) — a deliberate cache-bust marker noted in-code as "the GeoJSON property names changed," i.e. this endpoint's shape has already changed once since ship.

### 16.4 Cross-check against the JS's assumptions

- `apply_filters()`/`get_sections()` confirm the JS's `commonParams()` keys (`year, chemical, product, commodity, county, concern`) map 1:1 to server filter kwargs, with `chemical`/`product` validated as **integers** server-side (chem_code/prodno) — the JS never validates these client-side before sending them (they come straight from `data-chemical`/`data-product`, themselves server-rendered, so in practice always valid).
- The lens/all-sections per-township bucketing (`mtrs.slice(0, mtrs.lastIndexOf('-'))`, js:1639) depends on `properties.mtrs` being the section's full external_id with a trailing section suffix after a final hyphen — confirmed by `SectionListBase.get`: `'mtrs': section.external_id` (sections.py:223), and `TownshipListBase`'s township `id`/`name` being that same string minus the section suffix (townships are keyed by the MTR portion, sections.py:408 `township_geometries()`) — the convention holds, but it's an implicit string-format contract between two independently-maintained endpoints, not something enforced by a shared type; worth a comment or shared helper in the port.

