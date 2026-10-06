# Dairy region pages: design

Date: 2026-09-28
Branch: `feature/ceidars-explorer` (worktree `.claude/worktrees/feature+ceidars-explorer`)
Builds on: `2026-09-24-dairies-design.md`, `2026-09-24-emissions-areas-design.md`

## Why

An emissions region page (`emissions/area.html`) now carries the facility
stats, map, top facilities, sectors, trend, a full Dairies block (summary line,
top ten, three charts) and the "In and around" lists. Too much. The Dairies
block becomes its own page per area, laid out like the Dairies tab but scoped
to the area, and the region page keeps one line about dairies that links to it.

## Decisions

- **One dairy page per area, nested under the area's URL.** The region is the
  thing; dairies are a section of it. Breadcrumbs, `Region.get_*_url()` and
  the "In and around" lists all follow from that.
- **The Dairies tab's `?region=` and near-me filters redirect to the new
  pages.** One URL per view; the tab is the Valley-wide (or county-wide) view.
- **The tab keeps `?county=` as scope.** The scope bar changes the scope, never
  the page; the county dairy page is a different page (outline, breadcrumb,
  "In and around", no Counties choropleth), and the small overlap is fine.
- **The dairy pages light the Dairies tab** (`section = 'dairies'`); the
  emissions region page keeps no active tab, as now.
- **Dairies stay inside the emissions explorer.** See the last section.

## URLs

| Page | URL | Name |
| --- | --- | --- |
| Region dairies | `/tools/emissions/region/<sqid>/<slug>/dairies/` | `emissions:region-dairies` |
| Short form | `/tools/emissions/region/<sqid>/dairies/` → 301 to the slugged URL, query kept | `emissions:region-dairies-redirect` |
| Near-me dairies | `/tools/emissions/near/dairies/?lat=&lng=&radius=1\|3\|5&label=` | `emissions:near-me-dairies` |

`Region.get_emissions_dairies_url()` beside `get_emissions_url()`. The same
region types as `AREA_PAGE_TYPES`; anything else, a retired tract, or a region
without a boundary is a 404, and a wrong slug redirects, exactly as
`RegionPage` does. Near-me validates, cuts the label and bounces to
`emissions:home?find=1` exactly as `NearMe` does. Both lookups are pulled out
of `views.RegionPage` / `views.NearMe` into two small mixins
(`RegionLookupMixin`, `NearLookupMixin`) that the emissions and dairy pages
share, so the rules can't drift.

**Scope.** The query carries `year` and `pollutant` as every emissions page
does. The dairy pages resolve it with `dairies.resolve_scope()` (the tab's
rules): a year outside CADD falls back to the latest with a note, a pollutant
dairies don't report falls back to ROG with a note, `toxics`/`minor` are
dropped, and the request's GET is rewritten to the canonical query
(`dairy_views.canonical_query`) so every link on the page carries the
fallbacks. `county` is dropped (the page is the area), as `AreaPage.get` does.
The scope bar shows the county picker hidden and the disabled years,
pollutants and toggles with the tab's tooltips.

The table's own parameters (`q`, `sort`, `page`, `format=csv`) and the map's
(`view` is not offered here; `sizes`, `digester`, `tiles`) work as on the tab.

## The dairy page (`emissions/dairy-area.html`)

Top to bottom, for the resolved year:

1. **Header**: the area's name, type, county and population (the region page's
   header, `region_title` / `region_page_title`); near-me shows the radius
   buttons, which keep the query. Under it the fallback notes, if any.
2. **Headline stats**: the tab's four tiles (dairies with Large count, with a
   digester and share, milk cows and share, total cattle), moved into a shared
   include `emissions/includes/dairy-stats.html` that the tab uses too. County
   pages add a fifth tile, **Dairy cattle, CARB estimate**: tons/yr of the
   scope pollutant, with dairy cattle's share of the county's all-sources total
   as the small line (from `dairies.emissions_trend`). Other areas have no
   county figure and no fifth tile.
3. **Map**: the tab's dairy map (`dairy-map.js`), Dairies view only, with the
   size and digester filters and the Options menu; no view switch and no
   Counties choropleth (that is the tab's Valley-wide job). Framed on the
   area: `dairy-map.js` gains the facility map's `outline_url` / `center` /
   `zoom` / `radius` handling, drawing the outline mask or radius circle
   through the shared shell (`outline-mask` source), and fits the outline
   bounds. The points are the area's dairies only: the dairy GeoJSON endpoint
   gains `region=<sqid>` and `lat`/`lng`/`radius`, validated the way the
   table's filter is (`views.get_filter_region` with `dairy_views.FILTER_TYPES`
   plus counties, `views.radius_area`); an unknown region or bad point is a
   400. Response-cached per parameter set under the dairies generation key.
   A dairy counted by mailing city whose point sits outside the boundary still
   draws, under the wash, as facilities do; the outline is the frame, the
   membership rule (`RegionArea.dairy_q`) is the truth, and the table and map
   always agree because both use it.
4. **Table**: the tab's sortable table with name search, pagination, row-name
   zoom and CSV (`dairies-<area slug or near-lat-lng-radius>-<year>.csv`). No
   region picker and no near-me tag: the page is the area. County column
   hidden on county pages (`compact` stays the region page's top-ten shape;
   add a `hide_county` flag).
5. **Charts**: the herd trend and digester trend for the area; the CARB
   estimate chart on county pages only. Shared include
   `emissions/includes/dairy-charts.html`, used by the tab too. On a non-county
   page, one line under the charts: "CARB estimates dairy emissions by county:
   <County> dairies →" to the county's dairy page.
6. **In and around**: `regions/includes/within.html` with
   `nearby.regions_within(region, url_method='get_emissions_dairies_url',
   cache_prefix='emissions:within-dairies:v1')`, so every link is another
   area's dairy page. Near-me has none, as now. Tracts: same rule as today.
7. Footer line: the tab's "These are CARB's counts…" sentence.

No section nav: the page is one subject.

**Breadcrumbs.** `Emissions › <County> › <Area> › Dairies` — the county crumb
only when the area isn't the county, the area crumb linking to the emissions
region page, every crumb carrying `scope_qs`. Near-me:
`Emissions › Within 3 mi of <label> › Dairies`, the middle crumb linking to
the emissions near-me page with the same `lat`/`lng`/`radius`/`label`.

## What the emissions region page keeps

The Dairies block (`includes/dairy-block.html`) shrinks to a summary
(`includes/dairy-summary.html`), still at `#dairies` so the section nav
(Facilities · Dairies · In and around) is unchanged:

- Heading with the cow icon, then one line: "N dairies · N mature dairy cows ·
  N Large CAFOs · N with digesters", then **"Dairies in <name> →"** to the dairy
  page with the page's `year` and, when dairies report it, `pollutant`.
- County pages keep the one CARB line ("Dairy cattle, CARB estimate: 3,950
  tons/yr ROG"), greyed for NOx/SOx/CO as now.
- No top ten, no charts. `views.dairy_block()` drops `top`, `trend`,
  `digester_trend` and `emissions_trend`; `list_url` becomes `page_url`.
- Outside CADD's years: the greyed line as now, with "See 2023 →" linking to
  the *dairy page* at `year=<last_year>`.
- No dairies here: "No dairies in CARB's dairy database here." with no link,
  and the section nav drops the Dairies anchor as it does today.

## The Dairies tab

- `?region=<sqid>` → 301 to `emissions:region-dairies-redirect` for that sqid;
  `?lat=&lng=` (+`radius`, `label`) → 301 to `emissions:near-me-dairies`. The
  rest of the query (year, pollutant, q, sort, page, sizes, digester, tiles,
  measure) is carried; `view=counties` is dropped (the pages have no Counties
  view). An unknown or unsearchable `region` is dropped and the tab renders
  unfiltered, as it does today; bad `lat`/`lng` likewise. Why redirect rather
  than keep both: the filtered tab and the dairy page would be the same
  content at two URLs, one of them without the outline, breadcrumb or "In and
  around"; the region page's links, the find box and search engines should
  all land on one page.
- The sidebar's "City, community or ZIP" picker is replaced by the **Find your
  area** box (`find-area.js`), wired to dairy URLs: `find_area_places()` takes
  the URL method (cached under its own key), `data-near-url` is
  `emissions:near-me-dairies`, and its county jump links go to the county
  dairy pages with `find_area_qs`. Picking a place navigates; no redirect hop.
- `near_label`, `near_params`, `NEAR_KEYS` and the `region` filter in
  `table_filters` go; `FILTER_TYPES` moves to the GeoJSON endpoint's
  validation. The county scope, the Counties view and everything else stays.
- The home page's find box keeps pointing at the emissions region pages.

## Edge cases

- **No dairies in the area this year**: header and breadcrumbs, then one line
  "No dairies in CARB's dairy database in <name> for <year>." No stat row,
  map or table. The charts still render when any CADD year has a counted herd
  here (a dairy that closed); otherwise none. "In and around" stays. A county
  page still shows its CARB tile if CEPAM has a figure (a county with dairy
  emissions but no located dairies is possible in principle).
- **Year outside CADD** (`?year=2024`): the page shows 2023 with the tab's note
  and the canonical query; the scope bar's other years are disabled with the
  tooltip. The emissions region page's summary, which runs on the emissions
  scope, stays greyed for 2024 and links to the dairy page at 2023.
- **No CADD data at all** (before `import_cadd`): the pages render "No dairy
  data has been loaded yet." (200), the region page shows no summary, and the
  tab shows no find box.
- **County pages**: CARB tile, CARB chart and share as above; the map is
  framed on the county outline; the table hides the county column.
- **NOx, SOx, CO, toxics**: fall back to ROG with the note on every dairy page,
  so the CARB tile and chart on a county page are always for a reported
  pollutant; on non-county pages the pollutant only affects the links the page
  emits. The scope bar shows those options disabled with the tab's tooltips.
  The emissions region page's summary line is unchanged (greyed CARB line).
- **Near-me at a point in a county with no boundary data** or outside the
  covered counties: bounce, as the emissions near-me does.
- **Community areas with mailing-city members**: covered above; the smoke
  check clicks a circle under the wash.

## Tests (`camp/apps/emissions/tests/test_dairy_area_pages.py`)

- Routes: county, city, CDP, ZIP, tract dairy pages render; retired tract and
  other types 404; short URL and wrong slug redirect with the query kept;
  near-me renders, bad input bounces, a long label is cut.
- Scope: `?year=2024` shows 2023 with the note and rewritten links;
  `?pollutant=nox` shows ROG with the note; `?county=` is dropped; the scope
  bar's disabled options and tooltips; the county picker is hidden.
- Content: the four stat tiles match `dairies.summary(area=…)`; a county page
  has the CARB tile with the share and the CARB chart; a city page has neither
  and has the county link line; the table is the area's dairies in the
  default sort, sortable, searchable, paginated, county column hidden on
  county pages; the CSV rows and filename; herd and digester charts; the
  no-dairies line and its chart rule; "In and around" links are dairy URLs
  (and cached apart from the emissions lists); near-me has none; breadcrumbs
  for county, sub-county and near-me pages; `section == 'dairies'`.
- Map config: Dairies view only, `outline_url` on region pages,
  `center`/`zoom`/`radius` on near-me, the GeoJSON URL carries `region=` or
  the point.
- GeoJSON API: `region=` and the point narrow the features to
  `RegionArea.dairy_q` / `RadiusArea.dairy_q`; unknown region and bad point
  are 400; cached per parameter set and cleared by `clear_caches`.
- Tab: `?region=` and `?lat&lng` redirect with the query carried and
  `view=counties` dropped; unknown region renders unfiltered; the find box is
  present with dairy URLs; `test_region_filter*` and
  `test_near_me_filter_and_its_tag` become redirect tests.
- Region page: the summary line and its link (with and without `pollutant`),
  no table or charts, the greyed out-of-range link targets the dairy page, the
  no-dairies line; `SectionNavTests` unchanged.
- `Region.get_emissions_dairies_url()`.

## Smoke (`scripts/emissions_map_smoke.py`)

- Tulare County's dairy page: the dairy map loads, draws dairies, is outlined
  (`outlineBounds`); the legend has the size key; no view switch in the
  toolbar; the CARB chart is among the three charts; a table row's name zooms
  to its dairy with its popup; a year change (boosted swap) keeps one map.
- A community dairy page (a CDP or city with dairies): outlined, every drawn
  dairy is in the table's count, a circle under the wash still opens its popup.
- Near-me dairies: the circle draws; a radius button keeps the page and
  redraws.
- The tab with `?region=<sqid>` lands on the region's dairy page; the tab's
  find box takes you to a county dairy page.
- Tulare County's emissions page: the Dairies section is the summary only (no
  `.dairy-table`, no `.dairy-charts`), the "Dairies in Tulare County →" link
  goes to the dairy page, the section nav is unchanged.
- The retired checks (`Tulare County's Dairies block draws its three charts`,
  `with NOx, no CARB estimate chart`) move to the county dairy page.
- No console errors.

## Keep dairies in the emissions explorer

Keep them in. The dairy pages share the explorer's scope (year, pollutant,
county), its areas (`RegionArea`, `RadiusArea`, the region page types and
lookups, "In and around", find-your-area), its map core and its CARB county
inventory: the CARB dairy estimate *is* emissions data, from the same CEPAM
import the facility context bar uses. A separate explorer would duplicate the
home, about, find, region and near-me pages to hold one dataset with no
per-dairy emissions, and the two would still link each other on every county
page. The only real friction is the scope bar: a default pollutant (NOx) that
dairies don't report and half-disabled options. The fallback-with-a-note
handles that and is already built. Revisit only if dairies grow into a
livestock section with its own sources (Carbon Mapper plumes, ammonia,
feedlots); even then it is a second tab group under emissions, not a fourth
explorer.

## Out of scope

Dairy detail pages, dairies on the facility map or in the Areas choropleth,
per-dairy emission estimates, the Counties choropleth on region pages.
