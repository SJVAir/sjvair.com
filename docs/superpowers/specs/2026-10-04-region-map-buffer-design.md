# Region maps: "how far past the boundary"

**Status:** draft for review, 2026-10-04
**Branch:** feature/pesticides-explorer (PR #275); emissions (#282) adopts the shared helper.
**Asked by:** Derek, via the emissions session; confirmed here (map shows only inside the buffer).

## What

On a region's pesticides pages (county, city, ZIP, place, school district,
AB 617 community — every tab with a map: Overview, Notices, Records, Schools),
a toolbar control picks how far past the place's boundary the map reaches:
**Exact boundary · +1 mile · +3 miles · +5 miles** (`?buffer=0|1|3|5`,
default 0). The map shows only what's inside that area, frames it, and draws
its edge as a dashed line. Stats, tables and lists still count the place
exactly — only the map reaches past the boundary. Near-me pages don't get the
control: their 1/3/5-mile radius already is one.

## Shared: `camp/apps/regions/shapes.py` (both explorers)

- `BUFFERS = (0, 1, 3, 5)`.
- `buffer_param(params) -> int` — `params.get('buffer')` as an int in
  `BUFFERS`, else 0.
- `region_shape(region, miles=0) -> GEOSGeometry` (EPSG:4326) — the region's
  boundary; with `miles` > 0, widened in California Albers
  (`camp.utils.gis.EPSG_CALIFORNIA_ALBERS`) by `miles * 1609.344` m, simplified
  30 m (`preserve_topology=True`), back to 4326. Cached a day per region sqid
  and miles (as hex EWKB); miles=0 returns the boundary uncached.
- `buffer_options(request, current) -> [{'label', 'url', 'current'}]` — the
  page's URL with `buffer` set (0 drops the param) and `page` dropped; labels
  "Exact boundary", "+1 mile", "+3 miles", "+5 miles".
- Tests for each.

Emissions then points its `areas.map_shape` / `views.buffer_options` at these.

## Pesticides: the map honours the shape

- **Server.** Region area tabs read `buffer_param(request.GET)` and pass it to
  the map config: `region` (sqid) + `buffer` as the map's *clip area*, the
  widened shape's GeoJSON URL for the outline, and the toolbar options
  (`buffer_options`). The region's own outline stays as now; the widened edge
  is a second, dashed line (none at buffer 0). The map frames the widened
  shape. Every tab link and the scope bar carry `buffer` (like the year), so
  switching tabs keeps it; a page's own `?page=` is dropped when it changes.
- **API.** The map's layers take an optional clip — `region=<region sqid>` +
  `buffer=<miles>` (the names the emissions map APIs use) — and return only features inside `region_shape(...)`:
  sections (`sections/`), townships (`townships/`, so the valley-zoom grid
  doesn't paint outside), active and archived notices, and locations (which
  already take `region=`; add `buffer=`). It combines with `bbox` (the map
  still loads what's in view, clipped), is part of each endpoint's cache key
  (they cache on the full query string), and a bad sqid/buffer is a 400. A
  shared helper on the API side resolves `region`/`buffer` to the shape once.
  (Where an endpoint already reads `region=` as a filter — locations — the
  clip is that same region, widened by `buffer`.)
- **Map JS** (`assets/js/pesticides/section-map.js`): when the config carries
  a clip area, every layer fetch adds `region` + `buffer`; the initial fit
  frames the widened shape; the dashed edge is drawn in the region outline's
  colour, 1.5 px, dash [3, 3] (matching emissions). All-sections mode and the
  lens respect the clip (they fetch through the same calls).
- **Toolbar.** A "Map area" dropdown of plain links (the options above), in
  the map toolbar, on region tabs only — following how the emissions toolbar
  dropdown is built, but in the pesticides map's toolbar markup.

## Out of scope
Near-me pages, the main map, section/chemical/product pages, and changing any
stat or table to the widened area.

## Testing
- shapes.py: buffer parsing, widening (area grows; a point at 0.9 mi outside
  the boundary is inside the +1 shape, at 1.1 mi it isn't), caching,
  options' URLs (page dropped, buffer=0 dropped).
- API: each endpoint with `region`/`buffer` returns only features inside the
  shape; combines with bbox; bad input → 400.
- Views: region tabs put the clip, outline URL and options in `map_config`;
  tab links carry `buffer`; near-me tabs don't offer it.
- Smoke: a county and a city tab at buffer 0 and 3 — sections outside the
  shape aren't drawn, the dashed edge renders, the fit frames the shape.
