# Dairies in the Emissions Explorer: design

Date: 2026-09-24
Branch: `feature/ceidars-explorer` (worktree `.claude/worktrees/feature+ceidars-explorer`)

## Why

Dairies are a major Valley emission source that the facility inventory barely
sees: CEIDARS lists 13 livestock facilities, while CARB's California Dairy &
Livestock Database (CADD) has 1,558 Valley dairies (about 1.22 million milk
cows in 2023). No public dataset reports emissions per dairy, so this design
pairs CADD's counted facts (where each dairy is, its herd by year, its
digesters) with CARB's reported county-level dairy emissions, which we already
import (CEPAM). Nothing here is modeled per dairy.

## Sources

- **CADD v2.0.0** (CARB, XLSX; https://ww2.arb.ca.gov/california-dairy-livestock-database-cadd).
  Three sheets:
  - *Facility General Information* (2,115 statewide, 1,558 in the eight Valley
    counties): `CADDID`, `PlaceID`, `FacilityName`, `Latitude`, `Longitude`,
    `StreetAddress`, `City`, `County`, `ZipCode`, `RegionalWaterBoard`. Every
    Valley row has coordinates; `CADDID` and `PlaceID` are unique.
  - *Facility Herd Size* (note the trailing space in the sheet name): per
    `CADDID` and `Year` (2012–2023), `MilkCows`, `DryCows`, `OldHeifers`,
    `YoungHeifers`, `OldCalves`, `YoungCalves`, `BeefCattle`,
    `MilkCowsHerdSizeRefCode`, `NonMilkingCattleHerdSizeRefCode`,
    `LabeledAsDairy`. Reference code `1` is reported; others (`2a`–`3g`) are
    CARB's estimates and fills. Before 2019 only 1,309 Valley dairies have rows.
    A few counts are blank (treat as unknown, not zero).
  - *Anaerobic Digesters* (174 statewide, 164 Valley): `CADDID`,
    `OperationalYear`, `ShutdownYear` (`NaN` when operating), `DataSource`
    (DDRDP, AgSTAR, LCFS). A dairy can have several digesters; 8 have shut down.
- **CEPAM county inventory** (already imported as `CountyInventory`): rows with
  `source_name` LIVESTOCK HUSBANDRY and `subcategory_name` DAIRY CATTLE carry
  CARB's county dairy-cattle-waste emissions in tons/day for TOG, ROG, PM,
  PM10 and PM2.5 (NOx, SOx, CO are zero). Silage is reported separately and
  isn't attributed to animal type; it is excluded and footnoted. CEPAM has no
  ammonia.

## Decisions

- Dairies live in the `emissions` app (a third source beside CEIDARS and
  CEPAM), reusing its scope, areas, region pages and map glue.
- Herd size is measured in **EPA animal units** (40 CFR 122, Appendix B):
  mature dairy cattle (milk + dry cows) × 1.4, all other cattle (heifers,
  calves, beef) × 1.0. Labelled "Animal units (EPA)" with the formula in the
  about page and legends.
- Only counted or reported numbers; no per-dairy emission estimates.
- Carbon Mapper methane plumes are out of scope for now (possible later layer).

## Data model (`camp.apps.emissions`)

- `Dairy`: `sqid` (SqidsField), `cadd_id` (unique int), `place_id` (int),
  `name`, `address` (JSON: street, city, zipcode as given), `point`
  (PointField, 4326), `county` (FK to the county `Region`, resolved from CADD's
  county name; required), `water_board` (char), `cadd_version` (char, e.g.
  `2.0.0`).
- `DairyHerd`: `dairy` FK, `year`, `milk_cows`, `dry_cows`, `old_heifers`,
  `young_heifers`, `old_calves`, `young_calves`, `beef_cattle` (nullable ints),
  `milk_cows_ref_code`, `non_milking_ref_code` (char), `labeled_as_dairy`
  (bool), `animal_units` (float, computed at import from non-null counts).
  Unique on (`dairy`, `year`).
- `Digester`: `dairy` FK, `operational_year` (int), `shutdown_year` (nullable
  int), `source` (char). "Operating in year Y" = `operational_year <= Y` and
  (`shutdown_year` is null or `shutdown_year > Y`).
- Area membership is by the dairy's point, the same rule as facilities (county
  via the FK; city/place/ZIP/tract via point-in-boundary, with a cached
  dairy→ZIP/tract index like `region_index`). No ZIP or tract FKs.

## Import: `import_cadd`

- `--url` (default: the v2.0.0 file URL) or `--path` to a local XLSX, like
  `import_carbtac`; CARB changes the URL with each version.
- Reads the three sheets, keeps dairies whose county is in
  `settings.SJVAIR_COUNTIES`, upserts `Dairy` on `cadd_id`, replaces each
  dairy's `DairyHerd` and `Digester` rows. One transaction; idempotent.
- Unknown county names or missing coordinates are counted and reported, not
  fatal.
- Clears the dairy caches when done.

## The Dairies tab (`/tools/emissions/dairies/`)

A tab after Facilities and Sectors (duotone icon, its own colour).

**Scope bar on this page.** Options that don't apply are disabled, with a
tooltip: NOx, SOx and CO ("CARB reports no NOx from dairy cattle"), the toxics
and minor-source toggles, and years outside 2012–2023 ("CADD has herd data for
2012–2023"). A URL arriving with an invalid pollutant falls back to **ROG**,
and an invalid year to **2023**, each with a one-line note ("Dairies report no
NOx; showing ROG."). The fallback becomes the page's scope (so it's what scope
links carry onward). The county filter narrows the map and table.

**Headline numbers** for the year (and county): dairies, animal units, milk
cows, operating digesters.

**Map** (map core), toolbar **[Dairies | Counties]**:
- *Dairies*: amber circles sized by animal units, with a size key; dairies with
  an operating digester that year get an outlined ring. Popup (fetched on
  click): name, address, animal units, herd by class (estimated counts marked),
  digesters, "Counted in" links to the city/ZIP/tract region pages.
- *Counties*: a measure dropdown: **Dairy emissions** (the scope pollutant, from
  CEPAM dairy cattle, tons/yr) and **Herd size** (animal units), each also per
  square mile. Legend names the source ("CARB county inventory, dairy cattle
  waste; silage not included").
- View, measure and county state live in the URL with defaults left out, like
  the facility map.

**Table** under the map: name, city, county (links to its region page), animal
units, milk cows, other cattle, digester (yes/since year). Sortable by name,
city, county, animal units. Filters sit in the sidebar box the facility and
pesticides lists use: name search and the city/place/ZIP region picker
(point-in-region); also accepts near-me's `lat`/`lng`/`radius` (shown as a
removable "Within N mi of …" tag); paginated; CSV download. A row's name zooms the map to the
dairy and opens its popup. No dairy detail pages.

**Below the table**: a trend chart of total animal units and milk cows by year
with a marker at 2019 (coverage change), and a line linking to the about page.
For 2012–2018 a note under the map says CADD tracked fewer dairies before 2019,
so totals aren't a like-for-like comparison.

## Region and near-me pages

**Dairies block** after the facility sections:
- For the scope year: "N dairies · N animal units · N milk cows · N with
  digesters", the top 10 dairies by animal units (name, city, animal units,
  digester), and "All dairies here →" to the Dairies tab with `?region=` (or
  near-me's `lat`/`lng`/`radius`) applied.
- **Year outside 2012–2023**: the block is greyed with "No dairy data for
  2024. CARB's dairy database covers 2012–2023." and a "See 2023 →" link that
  changes only the year.
- **County pages** add CARB's dairy-cattle emissions for the county in the
  scope pollutant ("Dairy cattle, CARB estimate: 3,950 tons/yr ROG"). For NOx,
  SOx and CO that line is greyed: "No NOx data for dairies." Other area pages
  have no county figure, so the pollutant doesn't affect their block.
- An area with no dairies shows one line: "No dairies in CARB's dairy database
  here."

**Combined map** (the compact facility map on these pages, Facilities view
only): facilities and dairies as **same-size points**, coloured by value:
facilities on the existing blue ramp by tons of the scope pollutant (same
class breaks), dairies on an amber ramp by animal units (fixed classes, e.g.
<500, 500–1,500, 1,500–3,000, 3,000–6,000, 6,000+, checked against the real
distribution before fixing). Facilities draw above dairies. Legend: two small
ramps, "Facilities (tons/yr)" and "Dairies (animal units)". Same popups as the
facility map and Dairies tab. When the year is outside CADD's range, no dairy
points and no dairy ramp. The Areas (choropleth) view is unchanged and
emissions-only.

The main facility map (`/tools/emissions/map/`) is unchanged.

## API (`/api/2.0/emissions/dairies/`)

- `.../geojson/?year=` : dairy points with id, name, animal units, digester
  flag, county. Response-cached per year.
- `.../counties/?year=&pollutant=&measure=` : per-county dairy emissions
  (tons/yr and per sq mi) and animal units (total and per sq mi). Cached-endpoint
  pattern (un-cached base + cached subclass).
- `.../<sqid>/` : one dairy's herd breakdown for the year and its digesters, for
  the popup.
- Invalid year or pollutant → 400 with a message.

## About pages

- Emissions about page: a CADD section covering coverage, the EPA animal-unit
  formula, reference-code meanings, the pre-2019 caveat, why silage is excluded
  from the county dairy emissions, and that dairy numbers are counted/reported,
  not modeled.
- About/integrations page: CADD under Emissions Data.

## Error handling and edge cases

- Blank herd counts are unknown: excluded from sums and animal units, shown as
  "—".
- Dairies with no herd row for the selected year are left out of that year's
  map, table and totals (they may appear in other years).
- A digester's `ShutdownYear` of `NaN` is null (operating).
- CADD version bumps with column changes fail the import with a clear message
  naming the missing column, writing nothing.

## Testing

- **Import**: a small fixture XLSX: Valley-only filter, animal-unit math with
  blanks, idempotent re-run, multiple digesters, a shut-down digester, unknown
  county reported, missing column fails cleanly.
- **Stats**: point membership for ZIP/tract/radius, county dairy emissions =
  DAIRY CATTLE rows only (silage out), per-sq-mi, digester-operating-in-year.
- **Pages**: disabled scope options and their tooltips, ROG/2023 fallbacks and
  notes, the greyed region block (year) and greyed county emissions line
  (pollutant), table sorts/filters/CSV, empty-area line.
- **API**: each endpoint's shape, 400s, caching.
- **Browser smoke**: Dairies tab switch/measure/popup/row-zoom; a county region
  page's combined map legend and dairy popup.

## Out of scope

Per-dairy emission estimates; Carbon Mapper plumes; dairy detail pages; dairies
on the main facility map or in the Areas choropleth; ammonia (not in CEPAM).
