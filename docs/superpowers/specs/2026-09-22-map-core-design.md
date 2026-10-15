# Map core: one framework for SJVAir's MapTiler maps

Designed with Derek on 2026-09-22. Branch `feature/map-core` (worktree
`.claude/worktrees/feature+map-core`), branched from `feature/pesticides-explorer`
at `94a3794a`.

## Why

SJVAir has three maps on the MapTiler SDK (MapLibre GL), each a plain ES2017 IIFE
with its own global:

| Map | File | Lines | Used by |
|---|---|---|---|
| Pesticides section map | `assets/js/pesticides/section-map.js` | 3,650 | Pesticide Data Explorer (map, place, section, notice, records pages) |
| Admin/choropleth map figure | `assets/js/admin/map-figure.js` | 574 | Django admin change pages (`MapFigureMixin`), pesticides county choropleths |
| Emissions facility map | `assets/js/emissions/facility-map.js` (on `feature/ceidars-explorer`) | 709 | Facility Emissions Explorer |

They repeat the same helpers (style lookup, WebGL check, bounds, logging) and the same
htmx lifecycle (init on load and swap, adopt or release a map across swaps, drop
in-flight fetches). The facility map copies the pesticides chrome (zoom/locate/home,
toolbar, legend card, status pill, expanded mode) by duplicating its code and reusing
its `section-map-*` CSS classes. Every fix has to land three times, and each copy has
had its own lifecycle bug.

**Goal:** a shared core that owns the map shell and lifecycle, so each map is a module
holding only its own data logic, and a future map (the CADD dairy layer, NEI, ECHO)
gets the full chrome and lifecycle by registering a small module.

**Success:**
- All three maps run on the core.
- The pesticides map keeps every behaviour in its parity inventory
  (`docs/superpowers/specs/2026-09-21-section-map-inventory.md`).
- The three smoke scripts pass, and so does the full Django suite.
- A new map needs no chrome or lifecycle code of its own.

## Decisions (with Derek)

- **Scope: all three maps** (section map, map figure, facility map).
- **Branch:** `feature/map-core` off `feature/pesticides-explorer`. It merges back into
  pesticides after review, so PR #275 ships with it. `feature/ceidars-explorer` then
  merges pesticides and moves the facility map onto the core.
- **Packaging: plain scripts,** a set of IIFEs exposing `window.SJVAirMaps`, loaded by
  script tag before the map modules. No new build step; this matches the site's other JS.
- **Structure: a shell that maps plug into** (not a base class, not a helper library).

## Architecture

### Core scripts: `assets/js/maps/`

Loaded in this order by `camp/templates/maps/includes/scripts.html` (and by
`MapFigureMixin.Media` in the admin):

| File | Owns |
|---|---|
| `core.js` | `window.SJVAirMaps` namespace. Helpers now copied three times: `styleFor(id)` + `TILE_STYLE_PATHS`, `webglAvailable()`, `showUnavailable(el)`, `parseCenter('lat,lng')`, `parseBounds('w,s,e,n')`, `geometryBounds(geojson)`, `extendBounds`, `escapeHtml`, `isPhone()`, `prefersReducedMotion()`, `logger(prefix)`. |
| `controls.js` | `BarControl(className, label, icon, onClick)` and the stacked control set: SDK zoom (no compass), **locate** (geolocation → dot + ease + status; `onLocate` hook), **home** (shell's home framing). |
| `chrome.js` | Toolbar dropdowns (open, close on outside click, Escape, a click inside the menu keeps it open, closing any open popup); foldable panels (fold kept in `localStorage` per map name and panel, folded by default on phones); the status pill; expanded mode (`fitBelowNavbar`, pinned scope bar, scroll restore, Escape, `html.map-expanded`); lifting popups clear of the toolbar and panels. |
| `shell.js` | `Shell(el, name, spec)`: builds the SDK map from the container's `data-*` (key, style, center, zoom, bounds). It attaches the features the spec asks for, turns wheel-zoom on with a click and off when the pointer leaves, and folds the attribution on phones. It runs the module's hooks, and supplies `shell.ticket()` for stale-fetch guards and `shell.setStatus(text)`. Home framing: the module's `home()` if it has one, else the page center/zoom, else `data-bounds`. |
| `registry.js` | `SJVAirMaps.register(name, spec)` and `SJVAirMaps.init(root)`. It finds containers by `spec.selector` and runs one of two lifecycles: `'adopt'` (one live map per page, adopted in place across htmx swaps, released when no container is left) or `'figure'` (many per page, built lazily when scrolled into view, swept when their container leaves the document, never adopted). It also handles the WebGL fallback, idempotent init (`data-rendered`), and guarding against a second copy of the script after an htmx history restore (the map figure's existing guard). |

`SJVAirMaps.counties.bounds(geojson)` returns `{bySlug, all}` for the covered counties' outlines
(the one piece of county handling both explorer maps share). Each map keeps its own county layer
paint and framing: pesticides' framing (per-county fit, valley fit, settleFit) is its own logic.

### The module interface

```js
SJVAirMaps.register('facility', {
  selector: '.facility-map',
  lifecycle: 'adopt',                       // or 'figure'
  features: {
    controls: ['zoom', 'locate', 'home'],   // any subset, stacked top-left in this order
    toolbar: true,                          // filters + Options + Expand row (markup from the include)
    legend: true,                           // the foldable Legend card
    status: true,                           // the status pill
    expand: true,                           // expanded mode
    interactive: true,                      // false: no pan/zoom/rotate (map figures)
  },
  create: function (shell) {
    return {
      addLayers: function () {},            // sources + layers; runs on every style load
      load: function () {},                 // fetch data (shell.ticket(), shell.setStatus())
      onAdopt: function (changedKeys) {},   // data-* keys that changed across a swap
      onLocate: function (lngLat) {},       // optional: after the core's locate lands
      home: function () {},                 // optional: return {center, zoom} or {bounds}
      legend: function (bodyEl) {},         // fill the legend card's body
      destroy: function () {},
    };
  },
});
```

Every hook is optional. The shell calls `load` right after `create` (data set through
`shell.setSourceData` waits for the style), `addLayers` after every style load, `onChrome(wrap)`
at build and after every adopt (bind the module's own toolbar/Options controls), `onDropdownOpen()`
when a toolbar dropdown opens, `onAdopt(changedKeys, oldData)` after an adopt, and `legend(bodyEl)`
whenever the module calls `shell.updateLegend()`. A spec may also give `mapOptions(el)` (extra SDK
options, e.g. a figure's own view) and `panelStoragePrefix` (the localStorage prefix for panel folds).

### What each map keeps

- **`pesticides/section-map.js`** (module `section`, `adopt`, all features, Options in the
  toolbar):
  - **Stays in the module:** the township grid, square-mile sections and "all sections"
    canvas layer; the lens (hover a township → its 3×3 neighbourhood; prefetch ring;
    `LENS_FETCH_DELAY_MS`, `LENS_CLEAR_DELAY_MS`); notice and school/child-care markers
    and their popups; section popups; the Options contents (metric, notice/location/section
    toggles, tiles/ramp/bins experiment selectors); URL sync (`?metric=`, `?notices=`,
    `?sections=`, `?tiles=`, `?ramp=`, `?bins=`); the pending-fit/`settleFit` logic; the
    `DATA_KEYS` diff (now `onAdopt(changedKeys)`); `onLocate` (select the reader's
    square mile once the grid is drawn, the current `pendingLocate`); `home()` (page
    outline, else county, else valley); legend contents (county legend, level note,
    locations note).
  - **Moves to the core:** map construction, controls, toolbar binding, panels, status,
    expanded mode, scroll-zoom handling, attribution folding, popup clearance, WebGL
    fallback, `init`/`adopt`/`destroy`/`containersUnder`, and helpers. Expected removal:
    roughly 900–1,200 lines.
- **`admin/map-figure.js`** (module `figure`, `figure` lifecycle, `interactive: false`, no
  chrome): keeps areas, markers, hover labels and linked-area clicks. The lazy build,
  sweep, history-restore guard and helpers move to the core.
- **`emissions/facility-map.js`** (module `facility`, `adopt`, all features, sector dropdown
  in the toolbar), on `feature/ceidars-explorer`: keeps its circles (sqrt size, fixed
  log-scale classes), "none reported" rings, highlight, sector handler, popups and legend
  contents. Expected size about 250 lines.

### Templates

- **`camp/templates/maps/includes/map.html`**, used as
  `{% include 'maps/includes/map.html' with map=map_config %}`. It renders:
  - the wrapper (`map-wrap`, plus `is-compact` when `map.compact`);
  - the container, with its class from `map.container_class` and one `data-<key>`
    attribute per item in `map.data`;
  - when `map.features.toolbar` is on, the toolbar row: `map.toolbar_template` (the map's
    filters, if named), then an Options dropdown wrapping `map.options_template` (if
    named), then the Expand button;
  - the status pill;
  - when `map.features.legend` is on, the Legend card, with `map.legend_template` (if
    named) rendered inside its body.
  - The container also gets the class `map-canvas`, which the shared CSS sizes.
- **`camp/templates/maps/includes/scripts.html`**: the five core scripts in order.
- **Pesticides:**
  - `includes/section-map.html` becomes a thin wrapper around the include.
  - The Options menu contents move to `pesticides/includes/map-options.html`.
  - `pesticides/includes/map-toolbar.html` (its entity-picker filters) stays and is
    passed as `toolbar_template`.
- **Emissions:** the sector dropdown moves to `emissions/includes/map-toolbar.html`.
- **Map figures:** keep their own rendering (`camp.utils.mapfigure.MapFigure`); they have
  no chrome.

### CSS

- `assets/css/maps/map.css` takes the shared chrome rules out of
  `assets/css/pesticides/section-map.css`: toolbar, panels, controls, status, expanded
  mode, popup box and unavailable state.
- **Classes are renamed from `section-map-*` to `map-*`:**
  - `map-wrap`, `map-toolbar`, `map-toolbar-filters`, `map-toolbar-end`,
    `map-toolbar-dropdown`, `map-options`, `map-expand`
  - `map-panel`, `map-panel-head`, `map-panel-toggle`, `map-panel-body`,
    `map-legend-panel`
  - `map-status`, `map-locate`, `map-reset`, `map-note`
  - `html.map-expanded`
- **These keep their own stylesheets:**
  - pesticides: section/notice popups, lens, grid (`section-map.css`)
  - emissions: legend circles, facility popup (`facility-map.css`)
  - map figures: labels, markers (`admin/map-figure.css`)
- Explorer base templates and the admin load `maps/map.css`.
- **Also updated for the rename:** the class names in `pesticides.sass`,
  `entity-picker.js`, the pesticides templates and view tests, and the smoke scripts.

### Python

- **`camp/utils/mapconfig.py`** (not `maps.py`, which is the matplotlib static-map renderer):
  - `covered_bounds()` returns `'w,s,e,n'` around `Region.objects.counties()`, cached for
    a day. It moves here from emissions `views.covered_bounds()`.
  - `map_config(container_class, *, data, features, toolbar_template=None,
    options_template=None, compact=False)` returns the dict the include renders. It fills
    `data` with the shared keys: `maptiler-key` (`settings.MAPTILER_API_KEY`), `style`
    (default `'dataviz'`) and `bounds` (`covered_bounds()`), unless the caller sets them.
- Pesticides `section_map_config` and emissions `facility_map_config` build on
  `map_config`; their existing data keys are unchanged, apart from `bounds` being
  supplied centrally.

## Migration order

1. **Core:** the five scripts, `map.css`, the two includes, `camp/utils/mapconfig.py`, and
   Python tests for the include and config. No map uses the core yet.
2. **Map figure:** the smallest map, static, no chrome. It proves the `figure` lifecycle
   (lazy build, sweep, history-restore guard, WebGL fallback) on the admin and the county
   choropleths. `MapFigureMixin.Media` loads the core.
3. **Pesticides section map:** chrome and lifecycle out, data logic stays, class rename
   across templates, Sass, JS and tests. Pesticides parity is the gate: every inventory
   item is kept, and `scripts/pesticides_map_smoke.py` is extended with any inventory
   behaviour it doesn't check yet and passes in full.
4. **Review and merge:** Derek reviews on port 8002; `feature/map-core` merges into
   `feature/pesticides-explorer`.
5. **Facility map** (on `feature/ceidars-explorer`, after merging pesticides): the
   facility map moves onto the core; `scripts/emissions_map_smoke.py` passes; Derek
   reviews on port 8003.

## Testing

- **Python** (`django.test.TestCase`, plain `assert`):
  - `map_config` fills the shared keys and respects caller overrides.
  - `covered_bounds()` is cached and contains the counties.
  - The include renders the container's `data-*`, the toolbar and Options only when their
    templates are named, and the Legend card and Expand only when their features are on.
  - Existing pesticides and emissions view tests are updated for the `map-*` rename.
  - Admin map tests (`camp/utils/tests/test_admin_maps.py`) keep passing with the core
    in `Media`.
- **JS:** `node --check` on every script. There is no JS unit-test tooling in the repo,
  and adding it is out of scope.
- **Browser smoke scripts** (Selenium, run by hand), which are the acceptance bar:
  - `scripts/pesticides_map_smoke.py`: extended for any parity-inventory item it lacks.
  - `scripts/map_figure_smoke.py` (exists): choropleths build, hover and click, and the
    hidden-container build and swap leave exactly one live map.
  - `scripts/emissions_map_smoke.py`: after step 5.
- **The full Django suite** on each branch before each merge.
- **A visual pass with Derek** before each merge.

## Risks

- **Concurrent pesticides work:** if `section-map.js` keeps changing on
  `feature/pesticides-explorer` during this work, merging back will conflict. Merge
  `feature/map-core` back promptly after review, and merge pesticides into map-core
  first if it moves.
- **Behaviour drift in the pesticides map:** it has many subtle, deliberately ordered
  behaviours (listener binding order for the lens, `resize` firing `moveend`, adoption
  without rebuilding). The parity inventory and smoke script are the check. Any
  behaviour change found there is a regression unless Derek approves it.
- **Static JS isn't cache-busted:** hard-refresh after each change when testing by hand.

## Out of scope

- Moving the county-outline endpoint (`/api/2.0/pesticides/counties/`) to a neutral
  `regions` endpoint; a small follow-up.
- JS unit-test tooling.
- The home page's monitor map (a separate Vue app, `monitor-map/sjvairMonitorMap.js`).
- New map features. This is a refactor with parity; the facility map keeps what it has.
