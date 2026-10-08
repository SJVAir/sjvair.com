# The remaining maps on the MapTiler SDK

Approved (Derek, 2026-09-22): "let's switch all the other maps to maptiler-sdk then",
after the explorer's section map moved to the SDK. This covers every other map in
the repo, which is the one family built on `camp/utils/leaflet.py` +
`assets/js/admin/leaflet-maps.js`. When it lands, Leaflet is gone from SJVAir.

## 1. What these maps are

Non-interactive figures: a container with a GeoJSON payload beside it, turned into
a map in the browser (the server-side tile stitcher in `camp/utils/maps.py` was too
slow for admin pages, which is why they render client-side). Eight call sites, each
one map per page, plus the explorer's county choropleth:

| where | map |
|---|---|
| `camp/apps/regions/admin.py:73` | a boundary's geometry, one per `BoundaryInline` row (at most 2 versions per region today) |
| `camp/apps/regions/admin.py:171,204` | a region's boundary over its county, on the detail panels |
| `camp/apps/monitors/admin.py:150` | a monitor's position, zoom 15 |
| `camp/apps/ceidars/admin.py:126` | a facility's position |
| `camp/apps/reports/views.py:365,841` | valley-wide report maps, 800×800, ~1k simplified tract polygons and per-monitor markers |
| `camp/apps/pesticides/maps.py:174` | the county choropleth (`county_map`), on the explorer landing and entity pages and in the section map's `<noscript>` |

## 2. Parity list

Everything `assets/js/admin/leaflet-maps.js` does today, preserved:

1. **Non-interactive.** No dragging, wheel, double-click, box or keyboard zoom, no
   zoom control, attribution shown. Feature clicks and hover labels still work.
2. **Basemap.** MapTiler `dataviz`, with the `?tiles=<style>` experiment switch
   (same style ids as the section map; reuse its `styleFor()` mapping).
3. **Areas.** Polygons painted from `feature.properties.style`
   (`fillColor`, `fillOpacity`, `color`, `weight`), data-driven so one source and
   one fill plus one line layer serve every feature:
   `['get', 'fillColor', ['get', 'style']]` and friends.
   *(Amended after implementation: the four style keys are emitted flat on
   `properties`, read as `['get', 'fillColor']`. MapLibre re-serialises a nested
   property value to a JSON string on its way through `queryRenderedFeatures`,
   which warned on every hover and would hand a handler a string.)*
4. **Markers.** Points as the existing SVG shapes (circle, square, triangle, star)
   at `properties.size`, filled and stroked from those same keys, as
   `maptilersdk.Marker` with the shape's element (the direct analogue of Leaflet's
   `divIcon`). Interactive only when `labelOnHover` is true.
5. **Links.** An area with `properties.url` gets a pointer cursor and navigates on
   click.
6. **Labels.** `properties.label` renders as a label anchored at the feature,
   permanent unless `labelOnHover`, in the label class the CSS already styles.
7. **Fitting.** `fitBounds` over the payload with `padding` (the `data-padding`
   attribute); a single point instead centres at `data-zoom`.
8. **Lifecycle.** `init(root)` finds unrendered containers and is idempotent via
   `data-rendered`; exposed on `window` so htmx-swapped content renders the maps it
   brings. New for GL: maps whose container has left the DOM are `remove()`d on the
   next init, so repeated explorer navigation cannot leak WebGL contexts, and a map
   is created only when its container is first scrolled into view
   (`IntersectionObserver`), so an admin page with several below the fold is cheap.

## 3. Naming

Nothing should still claim to be Leaflet:

| now | becomes |
|---|---|
| `camp/utils/leaflet.py`, `LeafletMap` | `camp/utils/mapfigure.py`, `MapFigure` (`Marker`/`Area` keep their names and fields) |
| `LeafletMapMixin` (`camp/utils/admin.py`) | `MapFigureMixin` |
| `camp/templates/admin/_includes/leaflet_map.html` | `admin/_includes/map_figure.html` |
| `assets/js/admin/leaflet-maps.{js,css}` | `assets/js/admin/map-figure.{js,css}` |
| `window.SJVAirLeafletMaps` | `window.SJVAirMapFigures` |
| `.admin-leaflet-map`, `.admin-leaflet-label` | `.map-figure`, `.map-figure-label` |
| `camp/utils/tests/test_leaflet.py` | `camp/utils/tests/test_mapfigure.py` |

The container's `data-tiles` raster URL is replaced by `data-style` and
`data-maptiler-key`, as on the section map; `TILE_URL`/`TILE_ATTRIBUTION` go.

## 4. What this removes

- The vendored `assets/js/admin/leaflet/` and its `<script>`/`<link>` tags,
  including the ones in `camp/templates/pesticides/base.html` (the explorer then
  loads no Leaflet at all) and `camp/templates/admin/regions/region/change_form.html`.
  Leave `vite.config.ts` alone: its `leaflet` externals belong to the embedded
  monitor-map widget, not to these maps.
- `Leaflet` in `datafiles/technologies.yaml`, replaced by MapTiler SDK
  (`img/logo/tech/` needs a logo; use the MapTiler mark if one is there, else
  leave the entry's logo field pointing at an existing file and say so).
- `camp/apps/pesticides/tests/test_views.py`'s "keeps Leaflet for the choropleth"
  test, which becomes the opposite assertion.

## 5. Testing

Python tests cover the rendered container and its attributes, the mixin's media,
and every call site's template output (`camp/utils/tests/test_mapfigure.py`,
`camp/apps/reports/tests.py`, `camp/apps/pesticides/tests/test_maps.py` and
`test_views.py`). The browser side is checked with a small headless script in the
style of `scripts/pesticides_map_smoke.py`: the explorer landing page's choropleth
draws its eight counties, a county is clickable, and an htmx navigation away and
back leaves one live map.

## Global constraints

Worktree only, stage by name, no AI attribution or co-author trailers, do not push
(the controller pushes), Django TestCase + plain assert, `invoke styles` after Sass,
static assets are not cache-busted, dev server on :8002.
