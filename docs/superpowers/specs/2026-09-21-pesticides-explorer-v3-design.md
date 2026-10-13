# Pesticides Explorer v3: schools, trends, chemicals of concern

Three additions to the public Pesticides Data Explorer (`/tools/pesticides/`,
branch `feature/pesticides-explorer`). Approved by Derek on 2026-09-21
("schools, trends, chemicals of concern. Cruise through it all").

## 1. Locations: schools and child care on the map and the district pages

### Why
Parents and reporters ask "what is applied near the school". PUR is resolved
to the square-mile section, so the honest answer is the school's own section
plus the eight around it (the 3x3 block the map lens already uses), described
as "within about a mile".

### Data sources
| Type | Source | Coordinates | Filter |
|---|---|---|---|
| `public_school` | CDE Public Schools and Districts directory, tab-delimited `pubschls.txt` (https://www.cde.ca.gov/ds/si/ds/pubschls.asp; fields per fspubschls.asp: CDSCode, County, District, School, Street, City, Zip, Latitude, Longitude, StatusType, SOCType, EILCode/EILName, GSoffered, Virtual, OpenDate/ClosedDate, Charter) | in file | StatusType Active; `Virtual` not `F`; EILCode not `A` (adult); School non-empty (district rows have empty School); County in the eight SJV counties |
| `private_school` | CDE Private School Affidavit school-level XLSX/CSV for the latest year (https://www.cde.ca.gov/ds/si/ps/): school name, street, city, zip, county, enrollment, grade span | none: geocode | County in the eight SJV counties; enrollment >= 6 |
| `child_care` | CDSS Community Care Licensing facilities (data.ca.gov `community-care-licensing-facilities1`, GeoJSON/CSV): facility name, type, address, capacity, status, county, lat/lon | in file for centers; family child care homes carry city/zip only | Facility type in child care center kinds (Day Care Center, Infant Center, School Age Day Care Center); status Licensed; county in the eight. Family child care homes are **not** imported (no address) |

The eight counties: Fresno, Kern, Kings, Madera, Merced, San Joaquin,
Stanislaus, Tulare.

### Model: `regions.Location`
Points, not boundaries, so a new model rather than a Region.

```
class Location(TimeStampedModel):
    class Type(TextChoices): PUBLIC_SCHOOL, PRIVATE_SCHOOL, CHILD_CARE
    sqid = SqidsField(alphabet=shuffle_alphabet('regions.Location'))
    type = CharField(choices, db_index=True)
    name = CharField(200)
    external_id = CharField(64)         # CDS code / affidavit id / facility number
    source = CharField(32)              # 'cde-public', 'cde-private', 'cdss-ccl'
    address, city, zip = CharFields (blank allowed)
    point = PointField(srid=4326, geography=False, spatial_index=True)
    county = FK(Region, null=True, on_delete=SET_NULL, related_name='+', limit to type=county)
    district = FK(Region, null=True, on_delete=SET_NULL, related_name='schools', limit to type=school_district)
    metadata = JSONField(default=dict)  # grade span, school type, capacity, enrollment, source status
    imported_at = DateTimeField()
    unique_together = (source, external_id)
```
`county` is set spatially from the point (county boundary contains point).
`district` for public schools = the school-district Region whose
`external_id` (14-digit CDS) starts with the school's 7-digit district
code; for private schools and child care = the school-district Region
whose boundary contains the point (elementary/unified ambiguity: prefer
Unified, else the district containing the point with the widest grade
span; when none, null).

Admin: list display name/type/city/county, search by name, filter by type.

### Import: `import_locations` management command
`python manage.py import_locations --source cde-public|cde-private|cdss-ccl|all [--path FILE] [--no-geocode]`.
- Downloads the source when `--path` isn't given (URLs in the command;
  the CDE private-school URL changes per year, so `--path` is the normal
  route for it and the command says so in its help).
- Upserts by (source, external_id); rows that disappear from the source
  are deleted for that source (they closed). Idempotent.
- Geocodes only rows without coordinates, through `camp.utils.geocode.resolve`
  (MapTiler), with a cache keyed on the cleaned address (`cache` with a
  30-day TTL) so re-runs cost nothing. `--no-geocode` skips those rows.
- Prints counts: imported, updated, removed, geocoded, skipped (no
  coordinates), per source.
- Tests use small fixture files under `camp/apps/regions/tests/data/`
  (5–10 rows each) and never hit the network (geocode is patched).

### API: `/api/2.0/pesticides/locations/`
GeoJSON points. Params: `bbox` (required, capped like sections), `type`
(comma list of Location types; default all three). Properties: id (sqid),
name, type, address line, city, district name and sqid (when any), grade
span / capacity from metadata. Cached like the other map endpoints.

### Map
- An "Schools & child care" checkbox in the map Options menu (`?locations=1`,
  synced to the URL like `?sections=`). Off by default on the map page; on
  by default on school-district place pages.
- Markers: small circle markers on their own pane above the grid, distinct
  from the orange notice dots (use the site's records slate for schools,
  a purple for child care; document the colours next to the notice colour).
- Popup in the section-popup idiom: name; subline type · district; headline
  "N lbs applied within about a mile in 2023" fetched from the sections
  endpoint for the 3x3 block around the point (sum of the nine sections'
  metric, respecting the map's filters); actions: "Section details" for the
  containing section, "District page" when there is one.
- Loads by bbox on moveend like notices; only at zoom >= 9 (say so in the
  legend note when zoomed out with the toggle on).

### School district place pages
- A "Schools in this district" panel: table of the district's Locations
  (public and private schools, then child care), each with the 3x3-block
  pounds for the page's scope (year/all years, county), sorted most to
  least, linking to the section page. Computed server-side from the rollup
  (`camp/apps/pesticides/places.py`), cached like the other place stats.
- The page's map gets the locations toggle on by default.

## 2. Trend lines

### Where
The chemical, product, commodity, county and other place pages (everything
that already renders `by-year-table.html`), and the landing page (valley-wide
by year, from `PesticideUseTotal`).

### What
- A server-rendered inline SVG line chart above the by-year table: x = the
  loaded years, y = the page's metric (pounds by default; applications when
  the table is showing applications is out of scope — pounds only), with the
  selected year's point emphasised. No charting library. ~12 points. Prints.
  Include: `pesticides/includes/trend-chart.html` taking `by_year`, `year`,
  `hide_lbs`.
- A delta line under it: "Down 12% since 2019 · down 31% since 2014" —
  relative to the previous year and to the first loaded year, computed in
  `stats.trend_deltas(by_year, year)` returning `{'previous': {'year', 'pct'},
  'first': {...}}` with None when undefined (division by zero, single year).
  Wording: "Up"/"Down"/"Unchanged" (|pct| < 0.5 rounds to unchanged); under
  All years the reference is the first year only ("Down 31% since 2014").
- On placeholder-chemical pages (`hide_lbs`) the chart uses applications
  instead, labelled as such.

### Not
No section-level charts (one grower's rotation swings them). No client-side
charting.

## 3. Chemicals of concern as scope

### What
A third scope control beside year and county: a toggle "Chemicals of
concern" (`?concern=1`), carried in `scope_qs` and the hidden-input
include like the others. "Of concern" is the existing definition
(`stats._of_concern_query()`: Prop 65 categories, CARB TAC, IARC 1/2A/2B).

### Where it applies
- Lists: chemicals list restricted to concern chemicals; products list to
  products containing a concern chemical (via ProductChemical); commodities
  list to commodities with a concern chemical applied in scope. Pounds
  columns count concern-chemical pounds only (rollup rows with a concern
  chemical). Summary sentence says "… of concern".
- Map endpoints (sections, townships, section detail): rollup rows filtered
  to concern chemicals; `concern=1` param.
- Records: rows filtered to concern chemicals.
- Landing stats: totals, leaderboards and county table filtered (the
  "chemicals of concern" leaderboard becomes redundant under the toggle and
  is hidden then).
- Detail pages: a product/commodity page's numbers count concern-chemical
  pounds only and the related cards list only concern chemicals; a chemical
  page that is not of concern shows a note that the scope excludes it and
  renders unscoped (do not blank the page).
- Place pages and section pages: totals, by-month, top lists and the map
  follow the toggle.
- Notices: filtered to notices listing a concern chemical.

### UI
In the scope bar: a button-style toggle with the notices-style duotone
icon (fa-triangle-exclamation, orange primary), reading "Chemicals of
concern" and `is-set` when on, like the map toolbar's set state. A short
"what counts as of concern" tooltip (bulma-tooltip) listing the three
sources. Pages hide it where year is hidden? No: notices keep it (they
filter by chemical). Place/section pages keep it.

## Global constraints (bind every task)
- Work only in the worktree `/home/derek/dev/ccac/sjvair.com/.claude/worktrees/feature+pesticides-explorer`, branch `feature/pesticides-explorer`. Run every command from there. Never `cd` to the main checkout.
- Commit by naming files (`git add <files>`), never `git add -A`. No AI attribution or co-author trailers anywhere. Do not push.
- Tests: `docker compose run --rm test pytest <paths> -q`; Django `TestCase`, plain `assert`, `pytest.raises`. Fixtures via Django's fixture system (`fixtures/*.yaml`, `pesticides-explorer`).
- New models use `SqidsField` (see `camp/apps/ceidars/models.py`), never SmallUUID. Verbose names as first positional `_()` arg. Don't align `=`.
- Templates: Bulma styles; htmx-boosted navigation (`#explorer-body` swaps); products before chemicals wherever both appear; county names via `Region.short_name` in tables/pickers; keep "County" in prose.
- Static JS/CSS are not cache-busted; `dist/css/style.css` is git-ignored (rebuild with `docker compose run --rm web invoke styles`, never commit it).
- Sass `:root` custom properties need `#{$var}` interpolation.
- Scope: year (`?year=`), county (`?county=`), and now concern (`?concern=`) are carried by `stats.scope_param/scope_query` and `includes/scope-hidden.html`; pages read them through `year_context()` in `camp/apps/pesticides/views.py`.
- Map JS: `assets/js/pesticides/section-map.js` (plain ES2017, Leaflet 1.9, no build); the live map survives swaps via `SectionMap.adopt()`; URL view params via `syncViewParams()`; `commonParams()` is what every grid request sends.
- CDPR placeholder chemicals (`Chemical.PLACEHOLDER_CODES`) stay out of chemical rankings/counts (`stats.real_chemicals`).
