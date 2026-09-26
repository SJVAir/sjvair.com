# The explorer map on the MapTiler SDK

Approved direction (Derek, 2026-09-21): "lets get it", after the exploration
and the spike (`assets/js/pesticides/section-map-gl.js`, `?gl=1`). This spec
covers porting the Pesticides Explorer's interactive section map from Leaflet
to the MapTiler SDK (MapLibre GL), feature for feature.

## 1. Goal and scope

- The explorer's interactive map (`.section-map`, `section-map.js`) is
  reimplemented on the MapTiler SDK. Every behaviour in the parity checklist
  (`2026-09-21-section-map-inventory.md`, sections 1–14) is preserved unless
  this spec says otherwise. The DOM/data contract in
  `includes/section-map.html` and `views.section_map_config` stays the same,
  so the templates, the Python views and their tests do not change except
  where noted.
- Out of scope: the admin maps and the county choropleths rendered through
  `camp/utils/leaflet.py` + `assets/js/admin/leaflet-maps.js`. They stay on
  Leaflet (non-interactive, low volume; one session ≈ 17 raster requests, a
  wash for a single static map). The Leaflet script stays loaded on explorer
  pages only for those choropleths.
- Why: with the SDK a page load is one MapTiler session with unlimited
  interaction, where Leaflet pays per raster tile (42 on load, 60 after one
  zoom, measured); vector tiles are crisp on HiDPI and place labels sit above
  the choropleth; the monitor map is already on the SDK, so the platform
  converges on one map stack.

## 2. Delivery

- Groundwork already on the branch: `@maptiler/sdk` 4.1 and `esbuild` in
  `package.json`; `invoke bundle` (part of `invoke build`) rolls the SDK's ESM
  dist and its dependencies into `dist/maptiler-sdk/maptiler-sdk.js` (IIFE,
  global `maptilersdk`) plus `maptiler-sdk.css`; the spike loads that.
- The port is built as the real module `assets/js/pesticides/section-map.js`
  replacing the Leaflet one in place at the end, but developed as
  `section-map-gl.js` behind `?gl=1` (the spike's switch) until it reaches
  parity, so both maps can be compared on the same pages. The final task
  flips it: the GL module becomes `section-map.js`, the Leaflet module and the
  Leaflet-specific CSS are deleted from the explorer, the spike and the
  `?gl=` switch go, and `pesticides/base.html` loads the SDK bundle + CSS
  instead of Leaflet's (the admin `leaflet-maps.js`/`leaflet.css` stay,
  they're needed for the county choropleth).
- No parallel renderers survive (same principle as the uPlot charts).

## 3. Module architecture

`section-map-gl.js` is a plain script (no modules), same shape as today:
`window.PesticidesSectionMap = { init(root) }` discovered from explorer.js's
`htmx:load` hook; one live `SectionMap` instance, `data-rendered` guard, and
`adopt(newEl)` exactly as the inventory §12 describes: the live container
(with its GL canvas) physically replaces the freshly swapped-in one
(`replaceChild`), the `data-*` attributes are synced, and only what changed
is reloaded (`DATA_KEYS` → grid/notices/locations + lens cache reset;
outline/radius/view/county changes → their own updates; unchanged data →
legend/restyle only). `map.resize()` stands in for `invalidateSize()`. The
map is never torn down and rebuilt on a swap (the spike did; the real
module must not). A live map whose page no longer has a container is
`map.remove()`d, after `setExpanded(false)` when it was expanded (§12.2).

### Map creation
- `new maptilersdk.Map({ container, style, center, zoom, navigationControl:
  'top-left', geolocateControl: false, terrainControl: false, scrollZoom:
  false, attributionControl: compact, maptilerLogo: default })`. The SDK's
  navigation control replaces Leaflet's zoom control at the same corner; the
  toolbar row (Options, Expand, filters) keeps its DOM placement, so CSS that
  positions it relative to the zoom control is adjusted to the SDK's control
  size.
- API key: `maptilersdk.config.apiKey` from a new `data-maptiler-key`
  attribute (added to `section_map_config`), not parsed out of a tile URL.
  `data-tiles` is replaced by `data-style` carrying the style id
  (`dataviz` default); the `?tiles=` experiment switch maps ids straight to
  `maptilersdk.MapStyle` entries (the SDK catalogue contains every id the
  switch offers today: streets, basic-v2, bright-v2, dataviz, dataviz-light,
  topo-v2, outdoor-v2, toner-v2, hybrid). `views.section_map_config` and the
  admin helper's `TILE_URL` are untouched for the admin maps.
- Language: default. Projection: mercator. No globe, no terrain, no pitch
  (`pitchWithRotate: false`, `dragRotate: false`, `touchPitch: false`) so the
  map behaves like the flat Leaflet one.
- Reduced motion: every `fitBounds`/`easeTo`/`flyTo` passes
  `animate: !reducedMotion` (inventory §10).
- Scroll-wheel zoom: disabled until the map is clicked or focused, enabled
  then, disabled on mouseleave/blur, via `map.scrollZoom.enable()/disable()`.
  *(Amended 2026-09-24: click-to-arm is gone. The wheel arms while the cursor
  is deliberately over the whole `.map-wrap` -- chrome included, so reaching
  for Options or the Legend no longer disarms it -- and stays off when a page
  scroll merely slides the map under a still cursor. See the "wheel zoom"
  block in `assets/js/maps/shell.js`.)*
- Expand mode, scope-bar pinning, `fitBelowNavbar`: unchanged DOM/CSS logic,
  plus `map.resize()` after each size change (the SDK observes the container
  with ResizeObserver, but resize is called explicitly after toggles so the
  fit that follows measures the new size).
- WebGL unavailable (canvas `webgl2`/`webgl` context null): the container
  shows a short note ("This map needs WebGL…") and the page's other content
  is unaffected. No Leaflet fallback.

### Sources and layers (z-order bottom → top)
All data layers are inserted before the style's first `symbol` layer so
place labels render above them. Sources are GeoJSON with `promoteId: 'id'`
so feature-state keys on our ids.

| source | layers | data | notes |
|---|---|---|---|
| `counties` | `counties-line` | `data-counties-url` | county outlines (inventory §3); no fill |
| `grid` | `grid-fill`, `grid-line` | townships or sections for the view (`data-townships-url` / `data-sections-url` + `commonParams` + bbox; `geometry=0` values-only refetch with the cached township geometry, inventory §4) | fill colour/opacity from properties written client-side by the classing step (`fill`, `opacity`); line width by level; hover via `feature-state` |
| `all-sections` | `all-sections-fill`, `all-sections-line` | the visible townships' sections in "All sections" mode (`?sections=1`, 5×5 block fetches, inventory §5) | replaces the canvas renderer; `grid-fill` drops to opacity 0 while active, as today |
| `lens` | `lens-fill`, `lens-line` | the hovered township's 3×3 neighbourhood sections (inventory §5) | classed over the block |
| `lens-outline` | `lens-outline` | union outline of the lens hosts | |
| `selected` | `selected-line` | the selected section's geometry | the persistent selected-section outline (inventory §7) |
| `highlight` | `highlight-line` | `data-highlight` feature | orange 3px (inventory §3) |
| `outline` | `outline-line` | `data-outline-url` region outline | |
| `radius` | `radius-fill`, `radius-line` | the locate radius circle (built client-side as a polygon) | |
| `notices` | `notices-circle` | `data-notices-url` | circle layer, notice colour, white ring |
| `locations` | `locations-circle` | `data-locations-url` (bbox cap and unpadded fallback, inventory §8) | colour by `type` |
| `locate` | `locate-circle` | the geolocated point | the locate dot, on top of the markers (inventory §3.1) |

The true z-order is the inventory's §3.1 (radius sits with the grid at the
bottom; counties above the grid); this table lists sources, not paint order.
The navigation control is added by the module (`new
maptilersdk.NavigationControl({ showCompass: false })`, top-left) before the
Locate and Reset controls so they stack under it; the SDK's own
`navigationControl` option is off because it adds the control after the
first render, which would put ours above it.

Line seams and the zoom-dependent grid lines (`SECTION_LINES_MIN_ZOOM`,
inventory §3) become `line-width`/`line-opacity` expressions on zoom
(`['step', ['zoom'], 0, 10, width]`) rather than restyle passes. Hover,
selected and highlighted styling use `feature-state` and the dedicated
outline layers rather than per-feature `setStyle`/`bringToFront`.

### Interaction
- Hover: `mousemove`/`mouseleave` on `grid-fill` set `hover` feature state
  and drive the lens with the same timings as today (50 ms rest, clearing
  delays, `openLensId` rule).
- Clicks: `click` on `grid-fill`, `notices-circle`, `locations-circle`
  open `maptilersdk.Popup`s with the same HTML builders (township, section,
  notice, location popups; inventory §7), same CSS class hooks
  (`section-popup-wrap`), `closeOnClick: false`, one popup at a time,
  `reopenSelectedSection` after restyles. Popup-internal buttons (zoom in,
  district pill) bind as today.
- Cursor: pointer over interactive layers.
- Keyboard: the SDK's keyboard handler stays on; controls keep their
  `aria-label`s and `title`s (inventory §14).

### Data flow, classing, legend, URL sync
Unchanged from the inventory (§2, §4–§6, §11): `commonParams`, `covers()`
bounds cache, abortable grid requests, `quantileClasses`/ramps/bins, legend
DOM rendering, status line, `?metric=`/`?notices=`/`?locations=`/
`?sections=`/`?tiles=`/`?ramp=`/`?bins=` reading and pushing. The classing
step writes `fill`/`opacity` onto feature properties before `setData`, and
the legend reads the same class breaks.

### Controls
Locate and Reset become `IControl`s (`onAdd/onRemove`) placed top-left
under navigation, same icons and behaviour (geolocation flow, radius,
pending locate; `resetView` fitting valley / county / center+zoom).

## 3b. Pre-existing bugs fixed on the way (inventory findings)
- `SectionDetailBase.top()` (views.py) never sends `is_of_concern` for a
  section's top chemicals, so the section popup's orange "of concern" dot
  can never show. The port adds the field (with a test) so the popup works
  as designed.
- `LocationList`'s docstring says the bbox cap is 3°; the constant is 12°.
  Fix the docstring.
- The fallback centre/zoom (`[36.75, -119.80]`, 8) lives in both JS and
  `views.py`; the JS keeps its fallback but the view's values are the ones
  that reach the page through `data-center`/`data-zoom`.

## 4. Testing and verification

- Python: `views`/template tests unchanged except the config attribute
  changes (`data-maptiler-key`, `data-style`).
- Browser: a headless smoke script `scripts/pesticides_map_smoke.py`
  (selenium, tracked, dev-only, documented in its docstring) loads a place
  page, waits for the map's load, hovers for the lens, clicks for a popup,
  switches year through the scope bar, toggles notices/locations/all
  sections, and asserts no console errors and the expected feature counts.
  Implementers run it per task; reviewers run it too.
- Parity review: the final review checks the inventory line by line.

## 5. Sessions and cost

One `mtsid` per page load, shared across map instances (measured); htmx
swaps re-create the map without a new session. No per-interaction cost.

## Global constraints

Worktree only (`.claude/worktrees/feature+pesticides-explorer`), stage by
name, no AI attribution or co-author trailers, do not push (the controller
pushes), Django TestCase + plain assert for Python tests, Bulma, static JS
not cache-busted (hard refresh), `invoke bundle` + `invoke styles` after
Sass or bundle changes, dev server on :8002 (never 8000/8001).
