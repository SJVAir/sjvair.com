# Emissions explorer data expansion: design

Date: 2026-09-28
Branch: new branches stacked on `feature/ceidars-explorer`, one per phase (not
into PR #282; see `.superpowers/research/progress.md`).
Builds on: `2026-09-22-emissions-explorer-design.md`,
`2026-09-24-emissions-areas-design.md`, `2026-09-24-dairies-design.md`,
`2026-09-28-dairy-region-pages-design.md`.
Research: `.superpowers/research/{toxics,ammonia-ghg,compliance,oilgas-ces-schools}.md`
(all sources fetched and checked against the dev DB on 2026-09-28).

## Why

The explorer shows what permitted facilities report to CARB: criteria
pollutants and ten named toxics. Derek approved growing it in five directions:
toxicity-weighted toxics; CalEnviroScreen burden and schools near facilities;
compliance and violations; oil and gas plus greenhouse gases and methane; and
ammonia. This spec turns the research into nine phases, each a PR that ships
on its own and leaves the site whole.

## Assumptions

- The toxics unit fix has landed: toxics are stored and shown in lbs/yr
  (`pollutants.py` no longer multiplies by 2,000).
- Dairy region pages (`/tools/emissions/region/<sqid>/<slug>/dairies/`) exist
  as specified on 2026-09-28. There are no dairy detail pages, so anything
  per-dairy lands in the dairy table and popup.
- Every new model gets `sqid = SqidsField(alphabet=shuffle_alphabet('emissions.<Model>'))`
  beside the integer PK, as `camp/apps/emissions/models.py` does.
- Imports are management commands, idempotent, in one transaction per source
  (or per county), and they clear the explorer caches they affect. The ones
  with a live upstream feed also run as Huey periodic tasks on the `primary`
  queue under `lock_task`, following `camp/apps/pesticides/tasks.py`. The
  emissions app has no `tasks.py` yet; Phase 4 creates it.

## Shared: `SourceImport`

Phase 1 adds one small model every later phase uses for its "as of" stamp:

```
SourceImport: sqid, source (char, e.g. 'contable', 'icis-air'), imported_at,
              data_through (date, null), version (char, blank), notes (JSON)
SourceImport.latest(source) -> the newest row or None
```

Every import writes one row when it finishes. Templates read
`data_through`/`version` for the stamps below. No admin beyond list display.

## Data model summary

New in `camp/apps/emissions/models.py`, by phase:

| Phase | Models |
| --- | --- |
| 1 | `SourceImport`, `ToxicPollutant`, `ToxicEmission`; drops the 10 named toxic columns from `EmissionsRecord` |
| 2 | `Facility.point_source` |
| 3 | none (helper in `camp/apps/ces/stats.py`) |
| 4 | `AirComplianceFacility`, `ComplianceEvent` |
| 5 | `CountyNEI` |
| 6 | `DairyWaterEnrollment`, `DairyEnforcementAction` |
| 7 | `Well` |
| 8 | `GHGReport` |
| 9 | `MethaneSource`, `DigesterGrant` |

---

## Phase 1: Toxics in long format, weighted (M)

The ten fixed columns hold 1.2% of the Valley's toxic pounds and 31% of its
cancer-weighted total; diesel PM, the largest cancer driver, isn't stored.
This phase stores every toxic CARB reports per facility and weights it with
the potency table the Hot Spots program itself uses.

### Sources

- CARB facility detail CSV, per facility and year (exhaustive; the
  `showpol` sweep can miss an id):
  `https://www.arb.ca.gov/app/emsinv/iframe/facinfo/facdet_output.csv?&dbyr=<Y>&ab_=<SJV|MD>&dis_=<SJU|KER>&co_=<CO>&sort=T&facid_=<FACID>`
  Columns `FACID, CO, AB, DIS, POLLUTANT_ID, POLLUTANT, EMISSIONS_LBS_YR`.
  `ab_` is required: `SJU` → `SJV`, `KER` → `MD`.
- CARB/OEHHA Consolidated Table of health values (potency):
  `https://ww2.arb.ca.gov/sites/default/files/classic/toxics/healthval/contable.pdf`
  (19 pp, "last updated December 17, 2024"). Columns used: name (0), CAS or
  CARB code (1), acute REL (2), chronic REL (6), inhalation unit risk (10),
  MWAF (last). The dated URL `import_carbtac` uses returned 503; take
  `--path` or `--url` like `import_carbtac` does.
- Regression check only: CARB PMT `a24_toxtable3_2026_06_01.xlsx`
  (`https://www.arb.ca.gov/carbapps/pollution-map/data/`) gives CARB's own
  `CANC_SCORE`; Guardian Industries 2024 is 7,594.997.

### Models

```
ToxicPollutant
  sqid; carb_id (char 12, unique: a CAS without dashes, '71432', or a CARB
  code, '9901'); cas_number (dashed, blank for CARB codes); name; slug
  (for URLs, from name); kind: 'toxic' | 'precursor' (ammonia 7664417 only);
  iur (float, (µg/m³)⁻¹, null); chronic_rel, acute_rel (µg/m³, null);
  mwaf (float, default 1.0); weighted (bool, default True; False for CARB
  id 1150, "PAHs total with components reported", to avoid double counting);
  cancer_weight, chronic_weight, acute_weight (float, default 0; derived, see
  below); health_values_date (date, null).

ToxicEmission
  sqid; facility FK; year; pollutant FK; lbs (Decimal 25,15).
  unique (facility, year, pollutant); index (year, pollutant); index (pollutant, year).
```

Weights (CARB's method, reproduced to within 0.01% on 91 carcinogens):

- `cancer_weight = iur × mwaf × 7,700` when `weighted` and `iur` is set, else 0
- `chronic_weight = 0.01712 / chronic_rel` when set, else 0
- `acute_weight = 0.1712 / acute_rel` when set, else 0 (stored, not shown)
- CARB id 1151 (PAHs, no components) takes benzo(a)pyrene's IUR
  (`50328`) when the table gives it none: a one-entry override dict in
  `camp/apps/emissions/contable.py`.

Ammonia (7664417) is `kind='precursor'`: stored here because CARB delivers it
in the same feed, never weighted, never listed among toxics (Phase 5 shows it).

`EmissionsRecord` keeps `total_score`, `hra`, `chindex`, `ahindex` (verbose
names corrected: `chindex` is the chronic hazard index, `ahindex` the acute).

### Migrations

1. Create `SourceImport`, `ToxicPollutant`, `ToxicEmission`; rename the two
   verbose names.
2. Data migration: for each of the ten named columns, create a placeholder
   `ToxicPollutant` (carb_id from `ceidars.TOXIC_POLLUTANTS`, name from
   `pollutants.TOXICS`, no health values) and copy every non-null value into
   `ToxicEmission`. About 130k `EmissionsRecord` rows; runs in the deploy
   path in under a minute.
3. Drop the ten columns.

After deploy and before the crawl, the site shows exactly the ten toxics it
shows today, unweighted (no health values yet), so nothing regresses.

### Imports

`import_health_values --path | --url [URL]`

- Parses the PDF with pdfplumber. The parser lives in
  `camp/apps/emissions/contable.py` and accepts a 4-digit CARB code in the
  CAS cell as well as a dashed CAS (`import_carbtac` keeps its own parser for
  now; folding it onto this module is a later cleanup, noted in the PR).
- Upserts `ToxicPollutant` by `carb_id` (creating rows for every table entry,
  so the picker can name a pollutant before any facility reports it),
  recomputes the three weights, sets `health_values_date` from the PDF's
  "last updated" line, writes `SourceImport('contable', version=<date>)`.
- Idempotent. Cadence: manual, when CARB updates the table (check yearly).

`import_toxics --year Y [--county slug] [--workers 8]`

- For every `Facility` with an `EmissionsRecord` in `Y` (the facility list
  `import_ceidars` already built), fetches its facdet CSV; 8 workers, the
  `fetch_csv` retry/backoff from `ceidars.py`; a failed facility is
  reported and skipped, the county's other rows still land.
- Replaces the facility's `ToxicEmission` rows for `Y` with the CSV's
  (delete + bulk_create inside a transaction per county); unknown
  `POLLUTANT_ID`s create a `ToxicPollutant` with the CSV's name and no
  health values. Writes `SourceImport('ceidars-toxics', version=str(Y))`.
- ~8,650 requests per year; with 8 workers about 10 minutes. Backfill
  2010–2024 once (~2 hours, one-off dyno). Cadence: manual, after each
  year's `import_ceidars`, which the PR description documents beside it.
  Not a periodic task (neither is `import_ceidars`).

### Join and match rates

Rows join on `(CO, DIS, FACID)` exactly as `import_ceidars` does: 100%. The
2024 sweep found 309 toxics on 6,553 of 8,654 facilities (53,358 rows,
17.7M lbs). Health values match 172 of 308 pollutants covering 73.9% of
pounds and every top cancer driver (diesel PM, Cr(VI), naphthalene, cobalt,
benzene, PCBTF, formaldehyde).

### Scope and stats changes

- The toxics picker (`?toxics=1&pollutant=`) offers, in order: **Cancer-weighted
  (relative)** (`pollutant=cancer`, the new toxics default), **Non-cancer
  hazard (relative)** (`pollutant=chronic`), then every `kind='toxic'`
  pollutant with any Valley pounds in the scope year, ordered by its share
  of the cancer-weighted total, by `slug` (`pollutant=diesel-pm`). The ten
  old keys (`benzene`, …) redirect to their slugs.
- `stats.records()` splits: criteria read `EmissionsRecord` as now; toxics
  read `ToxicEmission` filtered by pollutant (value = `lbs`) or, for the two
  weighted measures, grouped by facility with
  `Sum(F('lbs') * F('pollutant__cancer_weight'))` (or `chronic_weight`).
  `totals`, `ranks`, `facility_table`, `sector_breakdown`, `county_breakdown`,
  `by_year`, `sector_trends`, `areas.area_values` and the facility GeoJSON
  all go through one `stats.values(scope)` → `(facility_id, value)` source, so
  the map, list, sectors, region pages and near-me get the new measures with
  no page-specific code.
- The weighted measures have no unit a person can read, so every surface
  shows them as **share of the Valley's total for that year** (percent) plus
  rank, never the raw number. In the Areas view, density and per-resident are
  disabled for them (tooltip: "Weighted toxics are shown as a share of the
  Valley total, not per square mile."). Circle sizes and choropleth classes
  use fixed share classes (0.01%, 0.1%, 1%, 5%, 20%).
- `SMALL_BASELINE_FLOOR` gains `'share': 0.0001` for the compare paths.
- `stats.toxics_breakdown(scope)`: the scope's cancer-weighted total by
  pollutant (top 8 + other), for the bar on the home page and region pages
  when the scope is toxics.

### What appears where

- **Home (toxics scope)**: headline numbers as now; below them a "What drives
  it" bar of the cancer-weighted breakdown by pollutant.
- **Facility page**: the toxics table becomes every pollutant the facility
  reported: name, lbs/yr, year before, share of the Valley's cancer-weighted
  total (or "no OEHHA cancer value"), a "non-cancer hazard" dot when
  `chronic_weight > 0`; sorted by cancer weight then pounds; the ammonia row
  is not in this table. A **Hot Spots (AB 2588)** card above it when any of
  the four fields is set:
  - Prioritization score `total_score`, with "High priority above 10";
  - HRA cancer risk `hra` "per million", with "public notification at 10,
    risk reduction required at 100";
  - Chronic and acute hazard index `chindex`, `ahindex`, with "1.0 is the
    reference level";
  - The CARB caveat and a link to the district's Air Toxics annual reports
    page (`https://www.valleyair.org/permitting/air-toxics-program/information-for-the-public/air-toxics-annual-reports/`).
  Confirm the hazard-index level against SJVAPCD's Hot Spots policy before
  the copy ships; if the district's notification level differs, use theirs.
- **Region and near-me pages (toxics scope)**: the breakdown bar under the top
  facilities table.
- **Map**: the legend names the measure ("Share of Valley cancer-weighted
  toxics, 2024").
- **About page**: a "Toxicity-weighted emissions" section: the formula, the
  table's date (`SourceImport('contable').version`), what is and isn't in it,
  the six caveats; and the source list gains the Consolidated Table.
  `pages/about/integrations.html`: OEHHA Consolidated Table under Emissions Data.

### Caveat copy

Panel title "What this is, and isn't", shown on the facility toxics table, the
map legend (short form) and the About page:

> **Not a health risk.** This ranks pounds released × how toxic each chemical
> is. It ignores stack height, weather, distance to homes and how long anyone
> is exposed. A tall stack in open land can score higher than a small source
> next to a school.
>
> **Relative, not absolute.** The number is a share of the Valley total. It
> has no units and isn't a risk "in a million".
>
> **The official measures are CARB's Hot Spots scores.** Where a facility
> has one, it's shown. As of the district's 2025 report, no Valley facility
> exceeds the public-notification threshold.
>
> **Toxics may be from earlier years.** CARB carries a facility's toxics
> forward from its last inventory.
>
> **Diesel PM here is from permitted stationary engines only.** Trucks,
> trains and farm equipment, the main sources of diesel exposure in the
> Valley, aren't permitted facilities.
>
> **Chemicals with no state cancer value count as zero.** Health values
> change: this uses OEHHA's table dated {date}.

### Tests

- `contable.py`: a two-page fixture PDF parses CAS and CARB-code rows, the
  four value columns, blanks, and the `TAC` suffix; weights follow the
  formulas; 1150 is unweighted; 1151 takes B(a)P's IUR.
- `import_toxics`: a stubbed facdet response replaces a facility's rows
  idempotently, creates an unknown pollutant, skips a failed facility and
  keeps the rest, writes `SourceImport`.
- Data migration: the ten columns copy to `ToxicEmission` and nothing else
  changes (`MigratorTestCase`-style, or a loaddata of the old fixture).
- Stats: `values()` for a pollutant, for `cancer` and `chronic`; shares sum to
  1; the Guardian regression fixture (its 2024 rows + table values → 7,595 ±
  1); ranks and Areas values for a weighted measure; the old picker keys
  redirect.
- Pages: facility toxics table order and flags; the Hot Spots card and its
  absence; the breakdown bar; the disabled Areas measures.
- Smoke (`scripts/emissions_map_smoke.py`): toxics scope with `cancer`,
  legend text, a popup share, the Areas view with density disabled.

### Deploy

1. `migrate` (creates, copies, drops).
2. `python manage.py import_health_values --path contable.pdf` (download the
   PDF by hand if `ww2.arb.ca.gov` 503s).
3. One-off dyno: `import_toxics --year 2024`, then the backfill years,
   newest first.
4. Clear the emissions cache (the command does it; a `CACHE_VERSION` bump in
   `stats.py` covers stragglers).

---

## Phase 2: Schools and child care near a facility (S)

### Sources

Already imported: `regions.Location` (CDE public and private schools, CDSS
licensed child-care centers; `import_locations`). 2,785 Valley locations.
No new download.

### Model change

`Facility.point_source` (char 16, blank): `census`, `carb`, `maptiler`,
`legacy` (the value the migration gives every existing point), '' for no
point. `import_ceidars` sets `census` or `maptiler` from which geocoder
answered (`geocode.resolve_batch` yields Census hits first; the command
knows which list an address came from), `clean_facility_points` sets
`census`/`carb`/keeps the current value per `locations.choose_point`'s
choice. A **trustworthy point** is `census` or `carb`.

### Query

`camp/apps/emissions/schools.py`: `near(facility)` returns
`{'within_1000ft': [...], 'within_quarter_mile': [...]}` of
`{location, feet}`, each list ordered by distance, using the bbox prefilter
then `distance_lte(D(ft=…))` pattern from `pesticides/places.point_area()`.
Distance in feet from `Location.point` to `Facility.point` (great-circle).
Cached per facility for a day. Returns None when the block is hidden.

Hidden when: no point; `point_source` not trustworthy; `sector` is `oil-gas`
or `refining-fuels` (district permit groupings whose points are mailing
addresses; 184 of 372 Kern oil-gas facilities have no point at all and the
rest aren't well locations); or the address fails `locations.is_geocodable`.

### What appears where

- **Facility page**: a card "Schools and child care nearby" beside "Where":
  two groups, "Within 1,000 ft" and "Within ¼ mile", each a list of name,
  type and distance (ten shown, "and N more"); "None within ¼ mile" when
  empty. The compact facility map draws a ¼-mile ring and the listed
  locations as small markers (a `points` overlay in `facility_map_config`).
- Nothing on region pages or the main map: 96% of Valley schools are within a
  mile of some facility, so an aggregate says nothing.
- **About page**: one paragraph on the two distances and their basis.

### Caveat copy

> Distances are straight lines from the school's map point to the
> facility's, not from property lines. 1,000 ft is the distance at which
> state law (Health & Safety Code 42301.6) requires the air district to
> notify parents before permitting a source of hazardous air emissions;
> ¼ mile is the distance school districts must review before siting a
> school (Education Code 17213). Being nearby isn't a measure of exposure.
> Child care covers licensed centers only, not family child-care homes.

### Tests

Fixture facilities and locations at 900 ft, 1,200 ft and 2,000 ft: the two
groups; ordering; hidden for `maptiler`/`legacy`/no point, for oil-gas and
refining-fuels, and for an ungeocodable address; `point_source` set by the
import and by `clean_facility_points`; the card renders and the map config
carries the ring and markers.

### Deploy

`migrate`; `clean_facility_points` (writes `point_source`; until it runs
every existing facility is `legacy` and the card is hidden).

---

## Phase 3: CalEnviroScreen on region pages (S–M)

### Sources

Already imported: `ces.CES5` (2026, 2020 tracts; DAC layer is the draft
2026 SB 535 list) and `ces.CES4`. No new download.

### Helper

`camp/apps/ces/stats.py`:

```
tract_summary(geometry, *, model=None) -> {
  'model', 'version', 'tracts': [{'region', 'ci_score_p', 'dac', 'population'}],
  'count', 'scored', 'dac_tracts', 'top25_tracts', 'population',
  'dac_population', 'dac_share', 'min_p', 'max_p', 'mean_p', 'containing'
}
```

- `model` defaults to the newest with rows (`CES5`, else `CES4`), on its
  current tract vintage, as `reports/views.ces_tracts()` picks today; the
  picker moves into `ces/stats.py` and reports imports it.
- Tract membership: a tract counts when it contains the geometry's centroid
  or the intersection covers at least 10% of the tract's area (California
  Albers). This keeps small places inside big rural tracts (Lost Hills,
  Arvin), which the centroid-in rule drops.
- **`ci_score_p = -999` is "no score"**: those tracts stay in `count` and in
  the DAC and population figures but are excluded from `scored`, `min_p`,
  `max_p`, `mean_p` and `top25_tracts`. This is the fix to
  `reports/panels.tract_stats`, which today averages the −999s in.
- `mean_p` is an unweighted mean of the scored tracts' percentiles, labelled
  as an SJVAir summary wherever shown. Population weighting waits for block
  population (not in this phase).
- `containing`: for a geometry smaller than one tract, that tract's row.
- `reports/panels.tract_stats()` is rewritten as a thin adapter over
  `tract_summary` keeping its keys (`avg_percentile` = `mean_p`).
- Cached per (model, geometry hash) for a day.

### What appears where

- **Region pages** (county, city, CDP, urban area, ZIP, school district) and
  **near-me**: a "Community" card under the headline numbers:
  - "X% of residents live in state-designated disadvantaged communities
    (SB 535)" (`dac_share`);
  - "N of M census tracts are in California's most burdened 25%
    (CalEnviroScreen 5.0)" (`top25_tracts`, `scored`);
  - the range "Tract percentiles run from A to B", each end linking to that
    tract's region page;
  - on a county page the card also lists the five highest tracts.
- **Tract pages**: the tract's own percentile, pollution-burden percentile,
  DAC status and category, with a link to OEHHA's CES map.
- **Facility page**: one line in "Where": "In a tract at the Nth
  percentile (CalEnviroScreen 5.0)", and "SB 535 disadvantaged community"
  when true, linking to the tract page.
- Not a map layer here; the Areas view stays emissions-only.
- **About page**: a "CalEnviroScreen" paragraph; integrations page already
  lists CES.

### Caveat copy

> CalEnviroScreen percentiles are OEHHA's, for census tracts, and rank
> tracts against the rest of California. Figures for a city, ZIP or county
> are SJVAir's summary of the tracts inside it, not an OEHHA score. The
> SB 535 disadvantaged-community list shown is CalEPA's 2026 draft until it
> is final.

### Tests

Geometry fixtures: a small place inside one tract (containing rule), a city
spanning tracts at 5% and 40% overlap (only the latter counts), a −999
tract (excluded from scores, kept in DAC and population), DAC share math,
top-25 count, the model picker falling back to CES4 when CES5 is empty;
`reports.tract_stats` keeps its keys and now ignores −999; the card on a
county, city and near-me page; the tract page block; the facility line.

### Deploy

No migration. Nothing to import. Re-run `import_ces5` when CalEPA finalises
the DAC list (existing command).

---

## Phase 4: Compliance: EPA ICIS-Air (M)

SJVAPCD publishes no enforcement data; its NOVs, settlements and inspections
reach the public only through EPA's ICIS-Air, and only for federally
reportable sources (~660 facilities, 70% of the Valley's permitted NOx).

### Sources

- `https://echo.epa.gov/files/echodownloads/ICIS-AIR_downloads.zip`
  (70 MB, refreshed weekly, public domain). Files used:
  `ICIS-AIR_FACILITIES.csv`, `ICIS-AIR_FCES_PCES.csv` (inspections),
  `ICIS-AIR_INFORMAL_ACTIONS.csv` (NOVs), `ICIS-AIR_FORMAL_ACTIONS.csv`
  (orders and settlements, `PENALTY_AMOUNT`),
  `ICIS-AIR_VIOLATION_HISTORY.csv` (HPV/FRV), `ICIS-AIR_PROGRAMS.csv`
  (Title V flag). Not `ECHO_EXPORTER.zip` (443 MB): its rollups are computed
  from the event files, its lat/lon isn't needed (matched facilities have
  our point) and the Detailed Facility Report URL is
  `https://echo.epa.gov/detailed-facility-report?fid=<REGISTRY_ID>`.
- Spot checks: `https://echodata.epa.gov/echo/dfr_rest_services.get_dfr?output=JSON&p_id=<REGISTRY_ID>`.

### Models

```
AirComplianceFacility
  sqid; facility FK (null; SET_NULL); pgm_sys_id (char 20, unique);
  registry_id (char 12); name; address (JSON: street, city, county, zip);
  pollutant_class (Major | Synthetic minor | Minor | ''); operating_status;
  title_v (bool); current_hpv (char 40); local_region (char 8);
  match_method ('parsed' | 'manual' | ''); reported_through (date, null;
  the newest event date for this facility).

ComplianceEvent
  sqid; icis_facility FK; kind ('inspection' | 'nov' | 'formal' | 'hpv');
  date; agency ('L' | 'S' | 'E'); action_type (char 80); description
  (text); penalty (Decimal 12,2, null); program (char 40, blank);
  pollutant (char 40, blank); resolved (date, null; hpv only);
  external_id (char 40).
  unique (icis_facility, kind, external_id); index (icis_facility, kind, date).
```

### Import: `import_icis_air [--path zip]`

- Streams the zip; keeps `STATE = CA` and `COUNTY_NAME` in
  `settings.SJVAIR_COUNTIES`; upserts facilities by `pgm_sys_id`, replaces
  each facility's events per kind (delete + bulk_create), in one transaction.
- **Join**: `PGM_SYS_ID` = `CA` + `SJV` + `0000` + 5-digit county FIPS +
  region letter (S/C/N) + facid, e.g. `CASJV00006029S3636` → Kern facid 3636.
  FIPS → CARB county: 019→10, 029→15, 031→16, 039→20, 047→24, 077→39,
  099→50, 107→54; district = SJVAPCD. `match_method='parsed'`.
  EKAPCD (`CAKCA…`) and EPA Region 9 ids don't encode our facid: a
  hand-kept dict in `camp/apps/emissions/icis_crosswalk.py`
  (`pgm_sys_id → (county_code, district_external_id, facid)`), empty in this
  PR, `match_method='manual'`. Unmatched rows are stored but never shown.
- Writes `SourceImport('icis-air', data_through=max event date)`.
- **Cadence**: monthly. `camp/apps/emissions/tasks.py`,
  `db_periodic_task(crontab(day='2', hour='11', minute='0'))` on `primary`
  under `lock_task('import-icis-air')`. The command is also runnable by hand.

### Match rates

663 SJVAPCD rows → 607 matched (92%); all 382 currently operating match. 56
unmatched are closed facilities. About 10 matched rows carry a previous
owner's name (Linn → Berry), shown with "as reported to EPA".

### What appears where

- **Facility page**: a card **"Compliance (federal Clean Air Act reporting)"**
  when the facility has any matched ICIS row:
  - badges: Title V / Major / Synthetic minor; current HPV status
    ("No violation identified" or "High-priority violation: addressed /
    unaddressed");
  - "Last 5 years: N inspections · N notices of violation · N formal
    actions, $X in penalties" (from `reported_through` back five years);
  - a dated table of events (kind, date, agency, description, penalty),
    newest first, 25 rows with "Show all";
  - "Full record at EPA ECHO →" (the DFR URL);
  - the stamp: "Reported to EPA through {data_through}."
  - When the facility has none: nothing. No "no violations" line anywhere,
    by design.
- **Facility list**: a filter "With an unaddressed high-priority violation"
  (`?compliance=hpv`), and a "Tracked by EPA" filter (`?compliance=any`).
- **Region and county pages**: one line under the top facilities table: "N
  of the M facilities here are tracked in EPA's air compliance system; K
  have an unaddressed high-priority violation →" (links to the filtered
  list). Nothing in map popups or table rows in this phase.
- **About page**: a "Compliance" section with the six caveats; integrations
  page: EPA ECHO / ICIS-Air under Emissions Data.

### Caveat copy

> **Only large sources are here.** About 660 of the Valley's 11,000
> permitted facilities are tracked in EPA's air compliance system. Smaller
> sources' inspections and violations aren't published anywhere. A facility
> with no compliance card isn't known to be in compliance.
>
> **The record runs late.** The district reports to EPA roughly a year or
> more behind. Recent quarters look quiet because they haven't been reported
> yet, not because violations stopped. Reported through {date}.
>
> **A notice of violation is an allegation.** Many are settled without any
> admission, and penalties are negotiated amounts.
>
> **Names are as reported to EPA** and may be a previous owner's.

### Tests

Fixture zip with a handful of rows: the Valley filter; the id parser on the
three real examples; an `S`, `C` and `N` id; an EKAPCD id left unmatched;
idempotent re-run replaces events; `reported_through` and `SourceImport`;
five-year rollups; the card, its absence, the list filters, the region
line; the periodic task calls the command under the lock.

### Deploy

`migrate`; one-off `import_icis_air`; the periodic task registers on the next
`huey_primary` restart.

---

## Phase 5: Ammonia (S–M)

Ammonia is a PM2.5 precursor (winter ammonium nitrate), not a toxic. Phase 1
already stores CEIDARS facility ammonia (CARB id 7664417, 427 facilities,
8.1M lbs in 2022). This phase shows it, and adds the county picture it
lacks: only 7 of 1,558 dairies report to CEIDARS, so facility ammonia is
about 3% of the Valley's.

### Sources

- Facility: `ToxicEmission` rows with `pollutant.carb_id = '7664417'` (Phase 1).
- County: EPA 2023 NEI (public domain, no key):
  - county × sector, all pollutants:
    `https://gaftp.epa.gov/air/nei/2023/data_summaries/eis_report_38706_county_Sector_allpolls_28aug26.zip`
    (97 MB zip; columns `fips code, county, sector, pollutant code, total
    emissions, emissions uom`);
  - nonpoint county × SCC, for the livestock split:
    `https://gaftp.epa.gov/air/nei/2023/data_summaries/2023nei_nonpoint_28aug2026.zip`
    (309 MB zip; `scc level-3` = "Dairy Cattle Waste", "Beef cattle waste",
    …).

### Model

```
CountyNEI
  sqid; county FK; year; pollutant (char 8, 'NH3' only for now);
  sector (char 128, EPA sector); subsector (char 128, blank; SCC level-3 for
  the livestock rows); tons (float).
  unique (county, year, pollutant, sector, subsector).
```

### Import: `import_nei --year 2023 [--sector-path zip] [--nonpoint-path zip]`

- Streams each zip's CSV row by row (never unpacked to disk), keeps
  `pollutant code = NH3` and the eight county FIPS; writes sector rows from
  the first file and `sector='Agriculture - Livestock Waste'` subsector rows
  from the second; one transaction; `SourceImport('nei', version='2023')`.
- Cadence: manual, per NEI release (every three years). No periodic task.

### Join

County FIPS → `Region` county (`external_id`): 8 of 8. Valley 2023 total
122,974 tons: livestock 59%, fertilizer 34%.

### What appears where

- **Picker**: "Ammonia (NH3)" joins the non-toxics list, in a group labelled
  "Precursor" under the criteria pollutants, shown in **tons/yr** (lbs ÷
  2,000, so it sits beside NOx and SOx). `stats.values()` reads
  `ToxicEmission` for it. Map, list, sectors, Areas, region pages and
  near-me follow with no page code.
- **Facility page**: an "Ammonia" row in the emissions table (tons/yr, county
  and sector ranks) when reported.
- **County pages and the home context bar (NH3 scope)**: the CEPAM context
  bar has no ammonia, so for NH3 it is replaced by an NEI bar: permitted
  facilities vs livestock (dairy / other) vs fertilizer vs everything else,
  with the year (2023).
- **County dairy pages**: a sixth tile, "Ammonia, EPA estimate: dairy cattle
  N tons/yr (P% of the county's ammonia)".
- **About page**: an "Ammonia" section; integrations page: EPA NEI under
  Emissions Data.

### Caveat copy

> Ammonia isn't toxic at these levels, but it reacts with other pollution to
> form fine particles (PM2.5), the Valley's main winter air problem. Most
> Valley ammonia, about 90%, comes from livestock and fertilizer that aren't
> permitted facilities; only 7 dairies report ammonia to CARB. County figures
> are EPA and CARB model estimates for 2023, not measurements.

### Tests

Streamed-zip fixture with rows for two Valley counties and one other:
filtering, subsector rows, idempotence; NH3 in the picker in tons; a
facility row; the NEI context bar on a county page and its absence for a
county without rows; the dairy tile.

### Deploy

`migrate`; one-off `import_nei --year 2023` (streams ~400 MB; run on a
dyno, ~10 minutes).

---

## Phase 6: Dairy Water Board compliance (S)

Dairy-facing; lands in the dairy tables and popups on the Dairies tab and the
dairy region pages. Air-district dairy compliance (Rule 4570) is not public;
this is water quality.

### Sources (data.ca.gov, SWRCB CIWQS, refreshed weekly/monthly, no key)

- Confined Animal Facilities: package
  `surface-water-water-quality-regulated-facility-information`, resource
  `c16335af-f2dc-41e6-a429-f19edba5b957` (datastore-active; use
  `https://data.ca.gov/api/3/action/datastore_search?resource_id=c16335af-f2dc-41e6-a429-f19edba5b957&filters={"region":"5"}` paged, or the dated CSV).
- Wastewater Enforcement Actions: package
  `surface-water-water-quality-regulatory-information`, resource
  `64f25cad-2e10-4a66-8368-79293f56c2f1` (46 MB CSV, 53k rows statewide).

### Models

```
DairyWaterEnrollment
  sqid; dairy FK; reg_measure_id (int, unique); reg_measure_type;
  order_number; program; wdid; status; effective_date; termination_date
  (null); cafo_type; cafo_subtype; cafo_population (int, null).

DairyEnforcementAction
  sqid; dairy FK; enforcement_id (int, unique); date; action_type (char 40);
  status; title; description (text); program; assessment (Decimal, null);
  paid (Decimal, null); oldest_violation (date, null).
  index (dairy, date).
```

### Import: `import_ciwqs_dairies`

- Loads the CAFO rows for region 5, and the enforcement CSV filtered to
  `FACILITY ID` in `Dairy.place_id`; upserts on the two ids; deletes rows no
  longer present; `SourceImport('ciwqs', data_through=max action date)`.
- **Join**: CADD `place_id` = CIWQS `facility_id`: 1,506 of 1,558 (97%),
  median point distance 9 m. 1,109 dairies have at least one action.
- Cadence: monthly periodic task (`crontab(day='3', hour='11')`).

### What appears where

- **Dairy table** (tab and dairy region pages): a column "Water Board
  actions" (count in the last 5 years, "—" for none); a filter "With a Water
  Board action in the last 5 years" (`?enforcement=5y`).
- **Dairy popup**: enrollment (order, status, WDID, reported herd), the last
  three actions (date, type, title), the 5-year count, "Record at CIWQS →"
  (`https://ciwqs.waterboards.ca.gov/ciwqs/readOnly/CiwqsReportServlet?inCommand=reset&reportName=RegulatedFacility&placeID=<place_id>`),
  the stamp.
- **Dairy region page headline**: a fifth (county: sixth) tile "N with a
  Water Board action since {year-5}".
- **About page**: a "Dairy compliance" paragraph; integrations: CIWQS.

### Caveat copy

> These are water-quality actions by the Central Valley Regional Water Board
> under the Dairy General Order (manure, lagoons, groundwater), not air
> violations. Air-district dairy permit compliance isn't public. A notice of
> violation is an allegation; many concern paperwork such as a late annual
> report. Reported through {date}.

### Tests

Fixture rows: the place_id join, an unmatched facility ignored, idempotent
replace, the 5-year count at a boundary date, the table column and filter,
the popup fields, the tile.

### Deploy

`migrate`; one-off `import_ciwqs_dairies`; task registers on restart.

---

## Phase 7: Oil and gas wells (M)

CEIDARS oil-gas "facilities" are district permit groupings covering whole
fields; their points are mailing addresses. Wells are where the activity is.

### Sources (CalGEM, CC-BY, no key)

- WellSTAR wells REST layer:
  `https://gis.conservation.ca.gov/server/rest/services/WellSTAR/Wells/MapServer/0/query`
  with `where=CountyName IN (...) AND WellStatus IN ('Active','Idle','New')`,
  `outFields=API,LeaseName,WellNumber,WellDesignation,WellStatus,WellType,WellTypeLabel,OperatorCode,OperatorName,FieldName,CountyName,Latitude,Longitude,SpudDate,inHPZ,isDirectionallyDrilled,GISSource`,
  `resultOffset` paging at 5,000 (66,443 Valley rows, 14 pages, ~1 minute).
  data.ca.gov package `wellstar-oil-and-gas-wells` documents it; its hub CSV
  lags the service (dated 2026-07-02) so the REST layer is the source.
- Not imported: field boundaries (`CalGEM/Admin_Bounds/MapServer/0`), HPZ
  polygons, production volumes (bulk ends 2021).

### Model

```
Well
  sqid; api (char 14, unique); lease_name; well_number; designation;
  status ('Active' | 'Idle' | 'New'); well_type; well_type_label;
  operator_code; operator_name; field_name; county FK; point;
  spud_date (null); in_hpz (char 24: 'Verified HPZ' | 'Uncertainty Area' |
  'Not Within HPZ' | ''); directional (bool); imported_at.
  index (county, status); spatial index on point.
```

### Import: `import_wells`

- Pages the REST layer, upserts on `api`, deletes Valley rows not returned
  (a well plugged or cancelled since drops out), `SourceImport('wellstar')`.
- Cadence: weekly periodic task (`crontab(day_of_week='0', hour='12')`).

### Join

None to CEIDARS (no shared key; don't try). Wells join regions by point
(county, ZIP, tract, city) through `areas.containing_region`, and
`Location`s by distance.

### What appears where

- **Main facility map and region/near-me maps**: an "Oil & gas wells"
  overlay checkbox in the legend (off by default; on by default on Kern
  County's page and the oil-gas sector page). Clustered circles coloured by
  status, a ring for `Verified HPZ`. Data from
  `GET /api/2.0/emissions/wells/geojson/` (all Valley wells, properties
  `id, s, h` only; cached a day; loaded only when the layer is on) with
  client-side clustering. Popup: lease and well number, status, type,
  operator, field, spud year, HPZ, "CalGEM record →"
  (`https://wellstar-public.conservation.ca.gov/WellSearch/Details?api=<API>`).
- **Region and near-me pages**: an "Oil & gas wells" line in the headline
  area when any: "N active · N idle · N in a verified health-protection zone
  (3,200 ft of homes or schools)". Hidden when zero.
- **Schools**: on region pages, "N schools and child-care centers here have
  an active or idle well within 3,200 ft" with the top ten by well count
  (`schools.wells_near_locations(area)`, cached). 92 locations Valley-wide,
  75 in Kern.
- **Kern callout**: on Kern County's region page and the oil-gas sector page,
  a computed sentence from CEIDARS for the scope year: "Oil & gas facilities
  reported P% of Kern's permitted-facility ROG and Q% of its benzene in
  {year}" (2024: 41% and 38%), plus the wells line.
- **Facility page (oil-gas sector)**: a note replacing the schools card:
  "This is a district permit grouping that can span a whole oil field. Its
  map point is the operator's address, not a well."
- **About page**: an "Oil and gas" section; integrations: CalGEM WellSTAR.

### Caveat copy

> Well counts are CalGEM's regulatory records, not emissions. Idle wells can
> still leak; plugged wells aren't shown. Health-protection-zone status is
> CalGEM's and is still being revised. Distances to schools are straight
> lines from the school's map point (the law measures from property lines).
> Oil & gas "facilities" in CARB's inventory are permit groupings that can
> cover a whole field; their map points aren't well locations.

### Tests

Stubbed REST pages: paging, upsert, removal of a well no longer returned;
region counts by point; the school 3,200-ft count with a fixture well at
3,000 and 3,400 ft; the GeoJSON endpoint's shape and cache; the Kern
sentence's arithmetic; the oil-gas facility note; smoke: toggle the overlay
on the map, click a cluster then a well.

### Deploy

`migrate`; one-off `import_wells`; task registers on restart.

---

## Phase 8: Greenhouse gases (M)

### Sources

- EPA GHGRP RY2023 via Envirofacts (public domain, no key; RY2023 is the
  latest; EPA has proposed ending the program, so this may be the last year):
  - facilities: `https://data.epa.gov/efservice/pub_dim_facility/state/CA/year/2023/JSON`
    (filter `county_fips` to the eight; 169 Valley rows, all with lat/lon and
    `frs_id`);
  - emissions: `https://data.epa.gov/efservice/pub_facts_sector_ghg_emission/facility_id/<id>/year/2023/JSON`
    (`gas_id`, `co2e_emission`);
  - FRS programs, for the join:
    `https://data.epa.gov/efservice/frs_program_facility/registry_id/<frs_id>/JSON`
    → the `AIR` id `CASJV0000…` parsed exactly as Phase 4 does.
- CARB MRR 2024 (XLSX, updated each November; needs a browser User-Agent):
  `https://ww2.arb.ca.gov/sites/default/files/classic/cc/reporting/ghg-rep/reported-data/2024-ghg-emissions-2025-11-04.xlsx`,
  sheets `2024 GHG Data` (header row 8) and `2024 Emissions by GHG`
  (`CO2, CH4, N2O` in metric tons of gas). `--path` or `--url`.

### Model

```
GHGReport
  sqid; program ('ghgrp' | 'mrr'); external_id (char 20: GHGRP facility_id
  or MRR ARB ID); year; facility FK (null); name; city; zip; naics (char 8);
  sector (char 128; GHGRP facility_types / MRR Industry Sector);
  subparts (char 128); co2e (float, metric tons; GHGRP total, MRR emitter
  CO2e non-biogenic + biogenic CO2 kept separate below); co2e_biogenic
  (float, null); ch4 (float, null; metric tons of CH4); n2o (float, null);
  point (null; GHGRP only); frs_id (char 12, blank); basin_wide (bool;
  MRR oil & gas production reported per basin); match_method ('frs' |
  'crosswalk' | 'auto' | '').
  unique (program, external_id, year).
```

### Imports

`import_ghgrp --year 2023`: the three Envirofacts calls (≈340 requests);
`match_method='frs'` when the FRS `AIR` id parses to one of our facilities,
else the crosswalk, else a distance-under-1-km-and-name match
(`match_method='auto'`), else unmatched. `SourceImport('ghgrp')`.

`import_mrr --year 2024 --path|--url`: keeps rows whose ZIP is a Valley ZIP
`Region`; uses only the *emitter* CO2e columns (never fuel-supplier or
electricity-importer totals); joins the per-gas sheet on ARB ID; marks
`basin_wide` for "San Joaquin Valley Basin" style oil & gas rows; matches
through `camp/apps/emissions/ghg_crosswalk.py` (ARB ID → facility key,
hand-curated for the top ~40 emitters in this PR) then name + ZIP auto match
with a conservative threshold. `SourceImport('mrr')`.

Both manual, yearly. No periodic task.

### Match rates

GHGRP: 87 of 169 by FRS, ~15 more by distance and name; the remaining ~65
are field-level oil & gas and Eastern Kern ids. MRR: 146 Valley emitters
(18.5 MMT CO2e); ~80% auto, the rest by crosswalk. Unmatched rows are shown
on county pages, never on a facility.

### What appears where

- **Facility page**: a card "Greenhouse gases": per program a line "{year}:
  N t CO2e (CH4 N t, N2O N t)" with "EPA GHGRP →"
  (`https://ghgdata.epa.gov/ghgp/service/facilityDetail/<year>?id=<facility_id>&et=undefined`)
  and "CARB MRR" links. Nothing when neither.
- **County pages**: "Largest greenhouse-gas reporters" table (top ten by
  CO2e, matched ones linking to their facility page, basin-wide oil & gas
  rows labelled "basin-wide, not one site"), with the two programs' years.
- **Facility list**: sort/filter not added; GHG isn't a scope pollutant.
- **About page**: a "Greenhouse gases" section; integrations: EPA GHGRP and
  CARB MRR.

### Caveat copy

> Greenhouse gases warm the climate; they aren't a local health measure.
> Only large emitters (about 10,000 t CO2e a year and up) report, so most
> facilities have none. Oil and gas production reports for a whole basin,
> not one site. Fuel sold by suppliers isn't counted here. Dairies don't
> report to either program.

### Tests

Stubbed Envirofacts JSON: the county filter, the FRS parse, an auto match
and a non-match; the MRR XLSX fixture: ZIP filter, emitter-only columns,
per-gas join, basin flag, crosswalk then auto; idempotence; the facility
card; the county table.

### Deploy

`migrate`; one-off `import_ghgrp --year 2023` and `import_mrr --year 2024
--path <xlsx>`.

---

## Phase 9: Methane: Carbon Mapper sources, digester grants (M)

### Sources

- Carbon Mapper public catalog (no key):
  `https://api.carbonmapper.org/api/v1/catalog/sources-csv?bbox=-121.6&bbox=34.8&bbox=-118.5&bbox=38.3`
  (columns `source_name, source_latitude, source_longitude, gas,
  observation_date_count, detection_date_count, source_persistence,
  source_emission, source_emission_uncertainty, ipcc_sector`; 728 CH4 and
  37 CO2 sources in the box on 2026-09-28). Plumes
  (`catalog/plumes/annotated`) aren't imported; the source is the durable
  unit and links to the plume viewer.
- CDFA DDRDP project list (PDF, updated 2026-06-27):
  `https://www.cdfa.ca.gov/oefi/DDRDP/docs/DDRDP_Project_Level_Data.pdf`
  (142 projects: dairy name, city, county, developer, grant, biogas end use,
  estimated annual MTCO2e reduction, dates). `--path` or `--url`.

### Licence (Carbon Mapper, `https://carbonmapper.org/terms`)

Custom non-commercial terms. What the site must do, in the spec so it isn't
lost:

- Show "Data by Carbon Mapper®" wherever the data is drawn or listed (map
  attribution control, the facility and dairy blocks, the About page), with
  a link to `https://carbonmapper.org`.
- Non-commercial use only. SJVAir is a non-profit public service; we do not
  sell or licence the data onward.
- Redistribution must carry the same terms: the GeoJSON endpoint's response
  includes `"license": "Carbon Mapper non-commercial terms, https://carbonmapper.org/terms"`
  and `"attribution": "Data by Carbon Mapper®"`; no CSV download of the
  methane layer in this phase; the public API docs state the terms.
- Don't present the numbers as ours: every emission rate is labelled
  "Carbon Mapper estimate".

### Models

```
MethaneSource
  sqid; source_name (char 64, unique); gas ('CH4' | 'CO2'); point;
  ipcc_sector (char 8); sector_label (char 32); persistence (float);
  emission_kg_h (float, null); uncertainty_kg_h (float, null);
  observations (int); detections (int); county FK (null, by point);
  dairy FK (null; nearest CADD dairy within 1 km); facility FK (null;
  nearest CEIDARS facility with a trustworthy point within 1 km);
  distance_m (float, null); fetched_at.

DigesterGrant
  sqid; dairy FK (null); project_name; dairy_name; city; county (char 32);
  developer; grant_amount (Decimal, null); end_use (char 64);
  est_reduction_tco2e (float, null); awarded (date, null); operational
  (date, null); match_method ('manual' | 'auto' | '').
```

### Imports

`import_carbon_mapper`: fetches the sources CSV for the Valley bbox, keeps
rows whose point is in a covered county, upserts on `source_name`, deletes
rows no longer returned, resolves the nearest dairy and facility (livestock
sources match dairies: 273 of 290 within 1 km; oil & gas sources match a
facility 141 of 395 times), `SourceImport('carbon-mapper')`. Monthly periodic
task (`crontab(day='4', hour='11')`).

`import_ddrdp --path|--url`: pdfplumber table parse; match to `Dairy` by
normalised name + city, then a hand-kept dict in
`camp/apps/emissions/ddrdp_crosswalk.py` for the misses; unmatched rows kept
and listed by county. Manual, when CDFA updates the list. Optional within the
phase: ship it only if the parse is clean in an afternoon; otherwise it
becomes its own small PR.

### What appears where

- **Maps** (facility map, dairy map, region and dairy-region maps): an
  overlay "Methane sources (Carbon Mapper)": circles sized by
  `emission_kg_h`, coloured by sector (livestock, oil & gas, waste). Popup:
  sector, rate ± uncertainty ("Carbon Mapper estimate"), persistence,
  observation and detection counts, nearest dairy or facility link,
  "View at Carbon Mapper →" (`https://data.carbonmapper.org/#<lat>,<lng>`),
  the attribution line. Endpoint `GET /api/2.0/emissions/methane/geojson/`.
- **Facility page**: a card "Methane plumes observed nearby" when a source is
  within 1 km: the rows above; hidden for oil-gas permit groupings (their
  point is an address) — instead the oil-gas sector page lists the Valley's
  oil & gas sources by field name where Carbon Mapper's name carries one.
- **Dairy popup and dairy tables**: a "Methane observed" marker with the
  rate and detection count; a filter "With an observed methane source"
  (`?methane=1`); the dairy region page headline gains "N with observed
  methane plumes".
- **Digester grants** (if shipped): in the dairy popup under digesters: "CDFA
  DDRDP grant, $X (year), estimated N t CO2e/yr reduction"; on county dairy
  pages, the county's total grants and claimed reductions.
- **About page**: a "Methane" section with the licence line; integrations:
  Carbon Mapper, CDFA DDRDP.

### Caveat copy

> Plumes are snapshots from aircraft and satellite passes. Each rate is an
> instantaneous estimate with wide uncertainty, not an annual total. A site
> with no plume hasn't been shown to be clean: it may not have been
> overflown, or the plume was below detection. Methane is a climate
> pollutant, not a direct local toxic. Data by Carbon Mapper®,
> for non-commercial use.

### Tests

Fixture CSV: the county clip, upsert and removal, nearest-dairy and
nearest-facility resolution with a 1-km boundary case, the trustworthy-point
rule; the GeoJSON endpoint carries `license` and `attribution`; the dairy
filter and headline; the facility card and its oil-gas suppression; the
DDRDP parse on a one-page fixture and its two match paths; smoke: the
overlay on the dairy map, a popup with the attribution.

### Deploy

`migrate`; one-off `import_carbon_mapper` and, if shipped, `import_ddrdp
--path <pdf>`; task registers on restart.

---

## Order and why

1. **Toxics long format** first: it corrects the biggest misreading on the
   site today (pounds ranking ammonia and solvents above diesel PM and
   Cr(VI)), it's the phase everything toxics-related depends on, and it
   carries the ammonia facility rows for free.
2. **Schools near a facility** and 3. **CES on region pages** next: both are
   small, need no new download, and answer the questions residents ask
   first ("is it near my kid's school", "is this a burdened community").
   CES also fixes a live bug in the admin reports.
4. **ICIS-Air compliance**: high public value, medium effort, and the first
   live feed with a periodic task; it also builds the id parser Phase 8
   reuses.
5. **Ammonia**: cheap once Phase 1 exists, and the NEI bar is what makes
   facility ammonia honest (3% of the Valley's).
6. **Dairy Water Board compliance**: small, and it lands on pages being built
   now.
7. **Wells**: medium effort, mostly Kern, valuable there; the overlay and
   school counts are self-contained.
8. **Greenhouse gases**: medium effort for ~170 facilities and a fuzzy
   crosswalk; a climate measure, less local than the rest.
9. **Methane** last: the licence needs Derek's nod, and the layer is most
   useful once dairies, wells and GHG are on the site to link it to.

Each phase is its own branch and PR stacked on `feature/ceidars-explorer`.
None depends on a later one; 5 and 9 read Phase 1's tables, 8 reuses
Phase 4's id parser (copy it if 8 ships first), 9's facility rule uses
Phase 2's `point_source` (fall back to "has a point" if 2 hasn't shipped).

## Open questions for Derek

1. **Carbon Mapper licence.** The terms are non-commercial with attribution
   and share-alike. SJVAir's use fits, but is a public GeoJSON endpoint that
   anyone can call "redistribution" you're comfortable with under those
   terms, or should the methane layer be served only to our own pages
   (same-origin, no documented API) until Carbon Mapper confirms in writing?
2. **Toxics default measure.** Making "Cancer-weighted (relative)" the
   default toxics view changes the headline names from auto-body shops and
   composters to Edwards AFB, Guardian glass, cement plants and diesel
   engines. That's the point, but it's a visible editorial choice. Default
   to it, or default to pounds with the weighted view one click away?
3. **Ammonia's home in the picker.** Putting it beside the criteria
   pollutants (in tons) is the only place the map and region pages can pick
   it up without new code, but it isn't a criteria pollutant. A "Precursor"
   sub-heading in the list, or a third toggle beside Criteria/Toxics?
4. **Wells: overlay or tab?** This spec makes wells an overlay on the
   existing maps plus region lines. A Kern oil-field view (field boundaries,
   wells per field, operators) would be a tab of its own; worth it, or not
   now?
5. **Compliance visibility.** The card is on the facility page and the list
   has a filter. Should HPV status also appear as a badge in facility tables
   and map popups (more visible, reads more like an accusation)?
6. **Toxics backfill depth.** 2010–2024 is ~130k requests to CARB (about two
   hours). All years, or the last five and extend on request?
