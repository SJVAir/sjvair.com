# Facility Emissions Explorer

A public explorer for permitted stationary-source emissions in the eight SJVAir
counties, at `/tools/emissions/`, built the same way as the Pesticide Data
Explorer (server-rendered Django + htmx, MapTiler SDK maps, uPlot charts).
Branch `feature/ceidars-explorer` (worktree `.claude/worktrees/feature+ceidars-explorer`), branched from `feature/pesticides-explorer`
at `d4449c6f` for its map, chart and htmx tooling. Designed with Derek on 2026-09-22.

**Database-driven, not SJV-hard-coded**. Which counties are covered comes from
`settings.SJVAIR_COUNTIES` and the imported county `Region`s; air districts are
`Region`s; nothing in the models, importers or views names SJV counties or districts.
SJV-specific wording lives only in templates (About page copy, headings).

Place pages ("what's near me", schools, districts) are out of scope: they come
later as a separate cross-dataset layer on top of `regions.Location`.

## Data sources

| Source | What | Access |
|---|---|---|
| **CEIDARS** (CARB facility inventory) | Per-facility annual emissions: 7 criteria pollutants + 10 named toxic air contaminants, tons/yr | `https://www.arb.ca.gov/app/emsinv/iframe/facinfo/{faccrit,factox}_output.csv?dbyr=<Y>&co_=<C>[&showpol=<CAS>]` (plain GET) |
| **CEPAM** (CARB county inventory) | County totals by emission inventory code (EIC) and source type (stationary / areawide / mobile / natural), tons/day, annual average | `https://www.arb.ca.gov/app/emsinv/iframe/2021/emsbyeic.csv?F_YR=<Y>&F_DIV=0&F_SEASON=A&SP=2019V104ADJ&SPN=2019V104ADJ&F_AREA=CO&F_COAB=&F_CO=<C>` (plain GET) |
| **CARB air district boundaries** | District polygons (`Air_District_Code` e.g. `SJU`, `KER`) | `https://services6.arcgis.com/x7ftScCDR8g2kVFB/arcgis/rest/services/Air_District_WFL1/FeatureServer/0/query` (ArcGIS REST, GeoJSON) |

Facts established while designing (all verified against the live endpoints):

- **Whole counties, two air districts.** Omitting CARB's area filters returns the whole
  county. Kern spans the San Joaquin Valley APCD (`SJU`) and the Eastern Kern
  APCD (`KER`): 1,788 + 212 facilities in 2024. Eastern
  Kern holds Kern's largest NOx sources (CalPortland Mojave 1,456 t, National
  Cement 691 t, Tehachapi Cement 341 t; the largest valley facility, Gallo Glass,
  is 230 t). The other seven counties are entirely SJU.
- **FACIDs are per district.** Kern reuses 10 FACIDs across SJU and KER in 2024
  (e.g. FACID 1 is a Bakersfield hospital and a Mojave quarry). Facility identity
  is `(county_code, air_district, facid)`, with `air_district` a foreign key to the
  district `Region`.
- **`PMT` is total PM, not PM2.5.** `PMT > PM10T` for 930 of 1,733 Fresno
  facilities in 2024. CEIDARS has no facility-level PM2.5. The existing `ceidars`
  model mislabels it `pm25`; `emissions` calls it `pm` ("Total PM").
- **Years.** CEIDARS serves 2000–2024 (2025 not yet published). Early years are
  sparse (Fresno: 273 facilities in 2000, 1,561 in 2010, 1,779 in 2024). Import
  **2010–2024**.
- **CARB's toxics summary scores** (`TS`, `HRA`, `CHINDEX`, `AHINDEX`) are blank for
  the SJV district. Keep the columns, don't surface them.
- **CEPAM is a projection.** Inventory `2019V104ADJ` (2019 SIP inventory) has base
  year 2017; every other year (2000–2050 available) is back-cast or projected
  ("grown and controlled"). Pages label it "CARB estimate (2017 base year)". Only
  whole-county requests work without a browser session (the form that splits a
  county by district sits behind bot protection); with whole-county CEIDARS that is what we want.
  Fresno 2017 NOx: 54.8 t/day, 77% mobile, 9% stationary, 7% areawide, 7% natural.
- **Concentration.** Top 10 facilities = 41% of valley stationary NOx, top 50 = 74%
  (2024, SJU only; Eastern Kern raises it further).

## App structure

`camp.apps.emissions` replaces `camp.apps.ceidars` (Derek: nothing consumes
`ceidars` beyond ingestion, so start fresh).

- **`emissions`** is a copy of `ceidars` (including the whole-county/`(district, facid)`
  importer fix already made on this branch) with a fresh `0001_initial`, new sqid
  alphabets (`shuffle_alphabet('emissions.Facility')` etc.), `pm25` renamed `pm`, the
  branch's `air_basin` field dropped (districts only), and
  the additions below. It holds both sources, like `pesticides` holds PUR and SprayDays:
  `models.py` (all models), `ceidars.py` / `cepam.py` (fetch/parse helpers),
  `sectors.py`, `stats.py` (aggregation), `views.py`, `urls.py`, templatetags.
- **`ceidars`** becomes a shell: `models.py` emptied, `admin.py`, commands and tests
  removed, and one new migration `0002` of `DeleteModel`s that drops its tables. It
  stays in `INSTALLED_APPS` until Derek deletes the app later. The uncommitted
  `ceidars/0002` migration on this branch is replaced by the
  delete migration.
- **API** moves from `/api/2.0/ceidars/` to `/api/2.0/emissions/` (`camp/api/v2/emissions/`);
  the `ceidars` API package is removed.
- **CLAUDE.md**: the sqids convention points at `camp/apps/ceidars/models.py`; repoint
  it at `camp/apps/emissions/models.py`.
- Command names stay source-named: `import_ceidars`, `ceidars_summary`, plus
  `import_cepam`, `assign_sectors`.

## Models

### `Facility`
Carried over from `ceidars.Facility`, plus:

```python
class Sector(models.TextChoices):        # see Sectors

air_district = ForeignKey('regions.Region', verbose_name=_('Air district'),
                          on_delete=PROTECT, related_name='district_facilities',
                          limit_choices_to={'type': Region.Type.AIR_DISTRICT})
sector = CharField(_('Sector'), max_length=32, choices=Sector.choices, default=Sector.OTHER, db_index=True)

class Meta:
    unique_together = [('county_code', 'air_district', 'facid')]
    verbose_name_plural = 'facilities'
```

`air_district` is part of the facility's identity (CARB assigns FACIDs per district, and
geocoding can fail or land on the wrong side of a boundary), so it comes from CARB's
`DIS` code, resolved to `Region(type=AIR_DISTRICT, external_id=DIS)` at import. It is
not derived from the point. `PROTECT` because deleting a district would orphan its
facilities' identity. `county` stays the existing nullable FK; `county_code` (CARB's
county number) stays the identity field. `is_minor_source` / `major_sources()` /
`minor_sources()` are unchanged (SIC 2711, 2752, 5541, 7216, 7532, 7538).

### `EmissionsRecord`
Facility x year, as in `ceidars`, with `pm25` renamed `pm` (`_('Total PM (tons/yr)')`).
Criteria: `tog, rog, co, nox, sox, pm, pm10`. Toxics (tons/yr, displayed as lbs/yr,
x 2000): `acetaldehyde, benzene, butadiene, carbon_tetrachloride, chromium_hexavalent,
dichlorobenzene, formaldehyde, methylene_chloride, naphthalene, perchloroethylene`.
Summary-score columns kept, not displayed. Unique `(facility, year)`.

### `CountyInventory` (CEPAM)

```python
class SourceType(models.TextChoices):
    STATIONARY = 'stationary'; AREAWIDE = 'areawide'; MOBILE = 'mobile'; NATURAL = 'natural'

county = FK('regions.Region', on_delete=CASCADE, related_name='+')   # type=county
year = IntegerField()
inventory = CharField(max_length=32)        # '2019V104ADJ'
source_type = CharField(choices=SourceType.choices, db_index=True)
eic = CharField(max_length=20)              # '010-005-0110-0000'
summary_name, source_name, material_name, subcategory_name = CharField(...)   # EICSUMN/EICSOUN/EICMATN/EICSUBN
tog, rog, co, nox, sox, pm, pm10, pm25 = FloatField(null=True)   # tons/day, as published
unique_together = [('county', 'year', 'inventory', 'eic')]
```

CSV `SRC_TYPE` maps `STATIONARY`/`AREAWIDE`/`MOBILE`/`NATURAL+UNPLANNED FIRE EVENT`
to the four choices; trailer rows (blank `EIC`) are skipped. About 2,400 rows per
county-year, ~290k for 8 counties x 15 years. Stored in tons/day; the stats layer
converts to tons/yr (x 365) when comparing with CEIDARS.

`INVENTORY = '2019V104ADJ'` is a constant in `cepam.py`, the one place to change
when CARB publishes a newer inventory.

### `regions.Region.Type.AIR_DISTRICT`
New choice `AIR_DISTRICT = 'air_district', _('Air District')` (under governmental
districts). `external_id` = CARB code; name and metadata from
`datafiles/air-districts.yaml` (see Importers).

## Sectors

`Facility.Sector` choices, with each sector's SIC codes and a one-line description in
`emissions/sectors.py`. `sector_for_sic(sic)` walks the list **in order and the first
match wins**, so specific sectors (glass, cement, refining, wineries) sit ahead of the
broad ranges that contain them. Codes are ints (`723` is SIC 0723); ranges are
inclusive `(low, high)` tuples. Anything unmatched, or a missing SIC, is `other`.

Built from the 2024 SIC distribution across the eight counties (445 SICs, 8,616
facilities); notable emitters called out per row.

| # | Slug | Label | SIC codes | Notes (2024) |
|---|---|---|---|---|
| 1 | `dairies-livestock` | Dairies & livestock | (200, 299) | 0241 dairies, 0211 feedlots: large ROG/PM |
| 2 | `farms` | Farms & orchards | (100, 199) | 0173 tree nuts |
| 3 | `crop-processing` | Crop processing & cotton gins | (700, 799) | 0723 (298 facilities), 0724 cotton gins |
| 4 | `oil-gas` | Oil & gas production | (1300, 1399) | 1311 (168), 1321, 1381–1389 |
| 5 | `mining` | Mining & quarries | (1000, 1299), (1400, 1499) | 1442 sand & gravel, 1474 US Borax |
| 6 | `glass` | Glass manufacturing | 3211, 3221, 3229, 3231 | Guardian, Vitro, Gallo, Ardagh, Owens-Brockway |
| 7 | `cement-minerals` | Cement, concrete & minerals | (3240, 3299) | 3241 cement (2,488 t NOx), 3273, 3296 |
| 8 | `refining-fuels` | Refineries, fuel terminals & pipelines | 2911, (2950, 2999), (4610, 4619), (4922, 4925), 5171, 5172 | |
| 9 | `wineries-beverages` | Wineries & beverages | (2080, 2087) | 2084 wineries: ~1,040 t ROG |
| 10 | `food-processing` | Food processing | (2000, 2099) | 2048 feed, 2022 cheese, 2034 dried fruit |
| 11 | `chemicals` | Chemicals & fertilizers | (2800, 2899) | 2875 fertilizer mixing (largely composting): ~1,700 t ROG |
| 12 | `power-plants` | Power plants | 4911, 4931, 4939, 4961 | |
| 13 | `waste-water` | Waste, water & recycling | (4940, 4959), 4971, 5093, 9511 | 4953 landfills |
| 14 | `telecom` | Telecommunications | (4800, 4899) | ~900 sites, mostly backup generators |
| 15 | `transportation` | Transportation & warehousing | (4000, 4799) | |
| 16 | `gas-stations` | Gas stations | 5541 | minor source |
| 17 | `auto-repair` | Auto body & repair | 7532, 7538 | minor source |
| 18 | `dry-cleaners` | Dry cleaners | 7216 | minor source |
| 19 | `manufacturing` | Other manufacturing | (2100, 2799), (3000, 3999) | wood, paper, printing (incl. minor 2711/2752), plastics, metal |
| 20 | `hospitals-schools` | Hospitals & schools | (8000, 8099), (8200, 8299) | |
| 21 | `government-military` | Government & military | (9100, 9999) | 9711 Edwards AFB, NAS Lemoore; 9199 (752) |
| 22 | `commercial` | Commercial & services | (5000, 5999), (6000, 6999), (7000, 7999), (8100, 8199), (8300, 8999) | |
| 23 | `other` | Other | everything else | construction (15–17), unknown SIC |

`TextChoices` member names are the slug upper-cased with `-` → `_`
(`DAIRIES_LIVESTOCK = 'dairies-livestock', _('Dairies & livestock')`). Descriptions
are one plain-language sentence each and live in `sectors.py` beside the codes.

Official SIC titles for display ("SIC 3221 · Glass Containers") come from
`datafiles/sic-codes.csv` (committed on this branch; the 1987 SIC manual as transcribed
in `saintsjd/sic4-list`, which covers all 445 SICs in the data), loaded once per
process by `sectors.sic_title(code)`.

`import_ceidars` sets `sector` on create and on the metadata-year update.
`assign_sectors` re-applies `sector_for_sic` to every facility after `sectors.py`
changes and reports how many changed. Adding a sector = new choice (a choices-only
`AlterField` migration, no DB work) + `assign_sectors`.

## Importers

- **Counties are configuration, not code.** The importers take their counties from
  `Region.objects.counties()` (the imported county `Region`s named in
  `settings.SJVAIR_COUNTIES`) and read CARB's county number from each one's
  `metadata['ca_county_code']`, which `import_counties` already stores ('10' for
  Fresno). This replaces the eight-entry `COUNTY_CODES` dict. `--county` takes a county
  slug (`fresno`). A county Region without `ca_county_code` is a command error telling
  the operator to re-run `import_counties`.
- **`import_ceidars --year Y [--county C] [--regeocode]`**: the whole-county version
  built on this branch (no area filters in the URLs; every lookup keyed by `(DIS, FACID)`;
  `air_district` resolved from the row's `DIS`) moved to `emissions`, plus `sector` and `pm`.
  Loads the district `Region`s by `external_id` once per run and **fails the county
  loudly** (command error listing the unknown codes) if a row's `DIS` has no imported
  district, telling the operator to run `import_air_districts` first. It never creates
  a placeholder district.
- **`import_cepam --year Y [--county C]`**: fetches `emsbyeic.csv` per county, replaces
  that `(county, year, inventory)` in one transaction (delete + bulk_create), idempotent.
  `--year` accepts a range (`2010-2024`).
- **`import_air_districts`** (in `regions`): queries the FeatureServer as GeoJSON,
  keeps districts intersecting the union of the covered county boundaries, and
  creates/updates the `Region` + current `Boundary` in place (like
  `import_forecast_zones`). Multi-part features with one code are unioned into a
  MultiPolygon. Idempotent. Name and metadata come from `datafiles/air-districts.yaml`
  (committed on this branch): all 35 California districts keyed by CARB code, with
  CARB's display name (`San Joaquin Valley APCD`, `Eastern Kern APCD`), `carb_url`
  (CARB's district profile page), `complaints_url` and `phone`, captured from
  https://ww2.arb.ca.gov/california-air-districts on 2026-09-22 and matched to the
  ArcGIS codes one-to-one. A code missing from the YAML falls back to the ArcGIS name,
  title-cased, with empty metadata. The ArcGIS layer has no URL or contact fields.

## Scope and URLs

Shared scope (querystring, carried by a scope bar like the pesticides one):

| Param | Values | Default |
|---|---|---|
| `year` | any imported year | latest |
| `county` | county `Region.slug` (as pesticides' `resolve_county`) | all configured counties |
| `pollutant` | `nox rog tog co sox pm10 pm` (criteria) or a toxic field name | `nox` |
| `toxics` | `1` switches the pollutant picker to the 10 toxics, in lbs/yr | off |
| `minor` | `1` includes minor sources in totals/rankings/map | off |

No "all years" scope: summing annual inventories isn't meaningful; trends cover it.

| URL (`/tools/emissions/…`) | Page |
|---|---|
| `` | Landing: scope totals, CARB context bar, top 10 facilities, top sectors, trend chart, facility search, link to map |
| `map/` | Full-page facility map |
| `facilities/` | Ranking table: sort by pollutant, filter county/sector/city/air district/name, sortable columns, pagination; `?format=csv` downloads the filtered rows |
| `facilities/<sqid>/<slug>/` | Facility page (`facilities/<sqid>/` redirects, as pesticides' `ExplorerRedirect`) |
| `sectors/` | All sectors: facility count, totals, share of stationary total, sparkline |
| `sectors/<slug>/` | Sector totals and trend, county breakdown, its facility table |
| `about/` | Coverage, gaps, districts, CEPAM caveat, units, minor sources, sources |

Formal name "Facility Emissions Explorer" in titles and headings; "CEIDARS" appears
only on the About page and in source notes.

### Landing
Headline totals for the scope and pollutant; the **CARB context bar**: a stacked
horizontal bar of the scope's CEPAM total by source type for the selected criteria
pollutant (converted to tons/yr), with the CEIDARS facility total alongside, and the
sentence "Permitted facilities in this inventory emit about N tons of NOx a year;
CARB estimates all sources in {county} emit about M tons (2017 base year)". Hidden
for toxics (CEPAM has no toxics). Then top 10 facilities (the shared facility table
component), top sectors, a by-year trend (uPlot line), the facility search picker,
and a map teaser linking to `/map/`.

### Facility page
- Header: name, address, city, county, sector (SIC code + title as secondary),
  "Regulated by <district>" (the district `Region`'s name, linked to its CARB profile
  page) with the district's phone number and a "Report an air pollution problem" link
  to its complaints page, all from the district `Region`'s metadata.
- Small map: the facility highlighted, neighbours faded.
- Criteria table for the scope year: tons/yr, rank in county, rank in sector, share of
  the county's CEIDARS stationary total.
- Trend chart (uPlot), every imported year, pollutant toggle.
- Toxics section in lbs/yr with year-over-year change; hidden when the facility
  reports none.
- Change note: when a pollutant changes by more than ±50% year over year, a note that
  large changes can reflect how emissions are estimated, not only real changes.
- Minor sources get pages, marked as minor, with the explanation linked to About.

### About
What CEIDARS is and isn't (permitted stationary sources only; not vehicles, farm
equipment, most areawide sources, most dairies, individual wells); the two air
districts and why Kern has both; CEPAM as a projection from a 2017 base year and its
Kern whole-county note; units (tons/yr, toxics in lbs/yr, CEPAM tons/day x 365);
"Total PM" vs PM10 and why there's no PM2.5; minor-source exclusion; year coverage
growth; sources and links.

## Aggregation (`emissions/stats.py`)

No rollup tables (~6,500 facilities x 15 years ~ 100k rows). Per-request aggregates
over `EmissionsRecord` joined to `Facility`, scoped by year/county/minor:

- `scope_totals(scope)`: per-pollutant sums and facility count.
- `ranked_facilities(scope, pollutant)`: queryset annotated with `Window(Rank())`
  over the scope, overall / by county / by sector.
- `sector_breakdown(scope, pollutant)`, `county_breakdown(scope, pollutant)`.
- `by_year(scope, pollutant)` for trends.
- `county_context(scope, pollutant)`: CEPAM sums by source type for the scope's
  counties and year, x 365, plus the CEIDARS total. If the year isn't imported for
  CEPAM, the context bar is omitted.

Results cached per scope for a day with a versioned key (`EMISSIONS_STATS_V1`), like
the pesticides `LANDING_KEY`.

## API (`/api/2.0/emissions/`)

- `` (facility list), `<sqid>/` (detail), `years/`: moved from `/api/2.0/ceidars/`
  unchanged apart from `pm` and the district/sector fields.
- `facilities/geojson/?year=&county=&pollutant=&toxics=&minor=&sector=`: every facility
  in scope with a point, properties `id, name, sector, value, rank` only (value in the
  pollutant's display unit). One request per scope (~6,500 features); cached via
  `CachedEndpointMixin`.
- `districts/`: simplified outlines of the air districts that have facilities.

Facility search is the facility list's `q` filter; there is no autocomplete endpoint
in this version.

Never linked from pages except via docs (pesticides rule).

## Map (`assets/js/emissions/facility-map.js`)

A new module on `@maptiler/sdk` (reusing the `invoke bundle` output, the
one-session-per-page-load pattern, and in-place adoption across htmx swaps from the
pesticides map). Not a port of `section-map.js`.

- One GeoJSON fetch per scope; changing scope refetches.
- Circle layer: radius ~ sqrt(value), clamped minimum so small sources stay
  clickable; colour by quantile bin over the scope (Blues, 6 bins, as pesticides);
  zero/missing value = small hollow grey dot; sorted so the largest draw on top;
  layers under the basemap labels.
- Hover: name + value. Click: popup (name, sector, value, county rank, facility page
  link), reusing the pesticides popup-clearance logic.
- Toolbar (URL-synced): pollutant, toxics, sector, minor sources. Legend: three
  reference circles + colour bins. Expand and locate buttons.
- Overlays: county outlines and the boundaries of every air district that has
  facilities in scope (`Region` type `air_district`, found through the FK).
- Compact mode for facility pages (the facility highlighted, neighbours faded) and
  sector pages (that sector only).
- No-JS: the map page links to the facility table.
- `scripts/emissions_map_smoke.py`: headless smoke test (selenium), run by hand.

Out of scope: clustering, heatmaps, lens, schools/child care, near-me, place pages,
enforcement/permit data, alerts.

## Testing

Django `TestCase`, pytest-style asserts, fixtures in `/fixtures/` (per CLAUDE.md).

- `import_ceidars`: whole-county URLs, same FACID in two districts, toxics on the
  right district, sector assignment, `pm`, idempotent re-run, metadata-year guard.
- `import_cepam`: parsing, source-type mapping, trailer rows skipped, idempotent,
  year replace.
- `import_air_districts`: county-intersection filter, multi-part union, website from
  the YAML, idempotent.
- `import_ceidars` with a `DIS` code that has no district `Region` fails that county
  with a clear error and writes nothing for it.
- County configuration: the importers cover exactly `settings.SJVAIR_COUNTIES`
  (override the setting in a test and check the requested CARB county numbers).
- `ceidars` 0002 drops its tables on a migrated DB.
- Sectors: every choice has SIC codes; ranges and the `OTHER` fallback;
  `assign_sectors` reports and changes only mismatched rows.
- Stats: totals, minor exclusion, ranks with ties, CEPAM x 365 share, lbs conversion.
- Views: every page for each scope combination; 404s for unknown sqid/sector; CSV;
  query-count assertions on list pages.
- API: geojson filters and property set; moved list/detail/years tests.

## Delivery

Spec, then an implementation plan, built task by task with per-task reviews:

Plan: `docs/superpowers/plans/2026-09-22-emissions-explorer.md`.

1. `Region.Type.AIR_DISTRICT` + `import_air_districts` (the facility FK needs it first).
2. `emissions` app (copy + fresh migration + `pm` + district FK + counties from Regions), `ceidars` delete migration, API move, CLAUDE.md.
3. Sectors: choices, `sectors.py`, SIC titles datafile, `assign_sectors`.
4. `CountyInventory` + `import_cepam`.
5. `pollutants.py` + `stats.py` aggregation layer.
6. Pages: landing, facilities list + CSV, facility detail, sectors, about.
7. `facility-map.js` + `/map/` + compact maps + GeoJSON endpoints.
8. Full suite, real-data pass, PR description with deploy steps.

Deploy steps (for the PR description): `migrate`; `import_air_districts` (before
`import_ceidars`, which needs the district `Region`s);
`import_ceidars --year Y` for 2010–2024; `import_cepam --year 2010-2024`;
`invoke build` (vendor, bundle, styles); flush the cache.

## Follow-ups (not in this project)

- **Official geometry for the Kern forecast zone.** `import_forecast_zones` derives
  "Kern (SJV Air Basin portion)" (`Region` CUSTOM, `external_id=sjvapcd-kern-airbasin`)
  by fitting SJVAPCD's forecast-map SVG to county boundaries. Once the district
  `Region`s exist, that zone is exactly Kern County ∩ the SJU district, so it can be
  recomputed from official boundaries (a new `Boundary` version). The Tulare valley and
  Sequoia zones are forecast areas inside SJU, not district lines, and still need the SVG.
- **CARB California Dairy & Livestock Database (CADD)** — its own spec and plan after
  this project (Derek, 2026-09-22). v2.0.0 (Oct 2025) is a directly downloadable XLSX:
  2,115 dairies (1,558 in the eight counties) with coordinates, herd size by class per
  year 2012–2023, and anaerobic digesters (164 of 174 statewide are in the SJV). No
  emissions; CEIDARS covers only 13 SJV livestock facilities, so CADD fills the gap
  rather than cross-referencing it. Show reported facts (location, herd, digesters,
  trend), not modeled emissions, in its first version.
