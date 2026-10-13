# Emissions by area: choropleth, region pages and near-me

Status: design approved in conversation 2026-09-24; this spec awaits Derek's review.
Branch: `feature/ceidars-explorer` (worktree `.claude/worktrees/feature+ceidars-explorer`).

## Why

The facility map answers "where are the plants"; it doesn't answer "how much is
emitted where I live". Three additions do:

- an **Areas** view of the map: counties, ZIP areas or census tracts shaded by
  the emissions of the facilities inside them;
- **region pages**, one per county, city, ZIP, place, school district or tract,
  modelled on the pesticides explorer's place pages;
- **near-me**, the same page for a point and a 1, 3 or 5 mile radius.

## Decisions (with Derek)

- **Choropleth, not a heatmap.** Shaded areas, not a smooth density surface.
- **One view at a time.** The map shows *Facilities* (the circles, default) or
  *Areas* (the choropleth), never both.
- **Levels: county, ZIP, tract.** No MTRS sections: they are how pesticide use is
  reported, not a geography people live in, and at a square mile the grid would
  mostly show single facilities as squares.
- **Measures: density (default), total, per resident.**
- **Population from the Census ACS 5-year estimate** (table B01003), for counties,
  ZIP areas and tracts.
- **Membership is by the facility's point.** A facility counts in the ZIP area
  or tract its point falls inside; county membership is CARB's county code (the
  existing `Facility.county` FK). No new foreign keys: facility data stays as
  imported. Measured locally: 14% of facilities' address ZIPs disagree with the
  ZIP area their point is in (380 within 250 m of the border; 384 over 5 km
  away), so address ZIPs would scatter facilities away from their dots.
- **Facility pages show both, labelled.** The address exactly as reported, and
  an "Area" line (county, ZIP area, tract) from the point, linking to the region
  pages it is counted in. Mismatches are the state's data, shown as given.
- **2020 census tracts everywhere in this work.** The database holds 980 tracts
  whose current boundary is 2020 and 183 retired tracts with only a 2010
  boundary (kept: CalEnviroScreen 4 references them). The choropleth, point
  assignment, tract pages, place search and population use 2020 tracts only, the
  vintage CalEnviroScreen 5 and the ACS use.
- **No air district pages.**
- **The UI follows the pesticides explorer** (routes, find-your-area search box,
  place page layout, outline mask, radius circle).

## 1. The Areas view of the map

**Toolbar.** A two-way switch, *Facilities | Areas*. In Areas two more controls
show: *Level* (county, ZIP default, tract) and *Measure* (density default, total,
per resident). View, level and measure are written to the URL
(`?view=areas&level=tract&measure=total`), omitted when default.

**What is shaded.** The same selection as the Facilities view: year, pollutant
(criteria or toxics), county scope, minor sources, sector. Each area's value is
the sum of that pollutant over the facilities inside it.

**Classes.** Fixed log-scale classes per measure and display unit (the facility
circles' approach), so a colour means the same amount across years and
pollutants. Areas with no facilities draw as an outline only. A region with no
population (or zero) has no per-resident value: "—" in the popup, unshaded.

**Legend.** The legend card follows the view: circle sizes and classes in
Facilities, area classes in Areas, plus a note of how many facilities have no
point (counted at county level only).

**Popup.** The area's name, facility count, all three measures, "Show
facilities" (switches to Facilities, zoomed to the area) and a link to the
region page.

**Framework.** The facility map module (`assets/js/emissions/facility-map.js`,
module `facility` on the map core) gains the areas source and layers and the
view switch; chrome (toolbar, legend card, popups) is the core's.

## 2. APIs

**Area values: `GET /api/2.0/emissions/areas/`.** Parameters: `level`
(`county|zipcode|tract`, required), the scope (`year`, `pollutant`, `toxics`,
`county`, `minor`) and `sector`. Returns
`{level, unit, facilities_without_point, areas: [{id, facilities, total, per_sq_mi, per_resident}]}`,
`id` being the Region sqid. Numbers only: no geometry. Cached a day per
parameter set.

- ZIP and tract: one grouped spatial query, facility points against the
  regions' boundaries (2020 tracts only).
- County: grouped by `Facility.county`.
- Region area (square miles) is computed once per region type from the full
  boundary, in California Albers, and cached.

**Shapes: `GET /api/2.0/regions/geojson/?type=…&simplify=1`.** The regions
GeoJSON endpoint added in `70bc14f5` gains a `simplify` flag. Simplified output
runs each type's boundaries through `shapely.coverage_simplify` together (Shapely
2.1 / GEOS 3.13 are in the image), so neighbours keep identical shared borders:
per-shape simplification is what doubled the county lines before. Tolerances:
about 50 m for ZIPs and tracts, finer for counties; tune so every type's payload
is well under 1 MB. Tracts are limited to 2020 boundaries (simplified or not).
The full-precision output stays for exact outlines.

Measured locally (rounded to 5 decimals): counties 851 KB full / 202 KB at
0.0005°; ZIPs 9.9 MB / 1.6 MB at 0.0005° / 959 KB at 0.001°; tracts need the
2020 filter before coverage simplification works (the mixed vintages overlap,
1.5× total area), and per-shape simplification alone takes them from 507k to 37k
vertices.

**Bug fix: `CachedEndpointMixin` must never fail a request on a cache write.**
Today a body over memcached's 1 MB item limit raises from `cache.set` and the
request returns 500 (seen on `regions/geojson/?type=zipcode` and `tract`). The
write is wrapped: on failure, log and serve the response uncached.

## 3. Region pages and near-me

**Routes.**
- `/tools/emissions/region/<sqid>/<slug>/` for counties, cities, ZIPs, places,
  school districts and 2020 tracts.
- `/tools/emissions/near/?lat=&lng=&radius=1|3|5`.

**Find your area.** The emissions home page gets the pesticides explorer's
search box (`find-area.js`): our region pages matched as you type, addresses
geocoded by MapTiler in the browser; the server never sees the query.

**Page, top to bottom.**
1. Header: name, type, containing county, population where known.
2. Headline numbers for the year and pollutant: facilities, total, per square
   mile, share of the county total.
3. Map (compact), framed on the region's outline with the outside washed out,
   or on the radius circle for near-me. Facilities/Areas works here; the
   default level is one step finer than the page (county page: ZIP; ZIP, city,
   place or school district page: tract; tract page: Facilities only).
4. Top facilities: the facility list's table, scoped to the area.
5. By sector: a bar chart of the area's emissions by sector, each bar linking
   to the sector page.
6. Trend 2010–2024: the area's total by year, stacked by sector.
7. County pages only: the CEPAM facilities-vs-everything-else context.

**Membership.** Point inside the boundary (region pages) or within the radius
(near-me). County pages use `Facility.county`. Facilities without a point
appear on county pages only.

**Scope bar.** Year, pollutant and minor sources carry over; the county picker
is hidden (the page is the area).

**Facility pages.** The "Area" line: county, ZIP area and tract from the point,
each linking to its region page; the address stays as reported.

## 4. Population

`python manage.py import_population` (in `regions`) loads ACS 5-year B01003
total population into `Region.metadata['population']` for counties, ZIP areas
(ZCTAs) and 2020 tracts, matched on GEOID. Idempotent; a deploy step; re-run
yearly when a new ACS release lands. No API key at this volume (one request per
geography type).

## Testing

- Unit:
  - area rollups by point, including a border facility and a facility with no point;
  - the three measures, including a region with no or zero population;
  - 2020-only tracts;
  - coverage simplification keeps shared borders identical;
  - `CachedEndpointMixin` serves uncached when the write raises;
  - `import_population` against a stubbed Census response;
  - region page, near-me and the facility "Area" links.
- Browser: `scripts/emissions_map_smoke.py` gains the Facilities/Areas switch,
  level and measure changes, the popup's "Show facilities", a region page and a
  near-me page.

## Deploy

No migrations: nothing in this design changes a model. Run `import_population`
once after deploying. Facility and region data are otherwise unchanged.

## Out of scope

CalEnviroScreen overlays, CADD dairies, NEI and ECHO, emissions-weighted
heatmaps, air district pages, and moving other explorers to 2020-only tracts.
