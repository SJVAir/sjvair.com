# Emissions Phase 5 (Ammonia) and Phase 7 (Oil and Gas Wells) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Two separable additions to the Facility Emissions Explorer, each its own PR. **Part A (Phase 5, Tasks 1–3):** ammonia becomes an explorer pollutant: the facility rows Phase 1 already stores (`ToxicEmission`, CARB id 7664417, `kind='precursor'`) show up in the picker beside the criteria pollutants in tons/yr, so the map, list, sectors, Areas view, region pages and near-me get it with no page code; and because only 7 of 1,558 dairies report ammonia to CARB (facility ammonia is about 3% of the Valley's), a new `CountyNEI` table from EPA's 2023 National Emissions Inventory gives every county page and the home page an "all sources" ammonia bar (dairy cattle / other livestock / fertilizer / everything else) and every county dairy page an "Ammonia, EPA estimate" tile. **Part B (Phase 7, Tasks 4–8):** CalGEM's WellSTAR wells (Active, Idle, New; about 66,000 in the Valley) are imported weekly into a `Well` table; the facility map, region, near-me and sector pages gain an "Oil & gas wells" overlay (clustered, coloured by status, a ring for a verified health-protection zone); region and near-me pages gain an "Oil & gas wells" section with counts, the schools and child-care centers with a well within 3,200 ft, and on Kern County's page (and the oil-gas sector page) a computed sentence about what the oil-gas permit groupings report; oil-gas facility pages say their point is an office, not a well.

**Architecture:**
- **Phase 5, data.** `camp/apps/emissions/nei.py` streams the two NEI zips (county × sector, all pollutants; nonpoint county × SCC for the livestock split) row by row out of the zip, never unpacked to disk, keeps `NH3` rows for the eight county FIPS codes, and writes `CountyNEI` (sector rows with `subsector=''`; livestock rows with `subsector=<SCC level 3>`) in one transaction with a `SourceImport('nei')` stamp. Its read side (`nei.context(scope)`, `nei.dairy_tile(county)`) is cached under `stats.prefix()`, so an import clears it with `stats.clear_caches()`.
- **Phase 5, the pollutant.** `pollutants.Pollutant` gains `carb_id`; `NH3 = Pollutant('nh3', 'NH3', 'Ammonia', carb_id='7664417')` lives in `PRECURSORS`, is in `POLLUTANTS`, is not toxic and has `unit == 'tons'`. `stats.value_expr()` reads it from `ToxicEmission` ÷ 2,000; everything downstream (`valued`, `values`, `totals['value']`, `ranks`, `facility_table`, breakdowns, `by_year`, `area_values`, the GeoJSON) already goes through `value_expr`. `county_context()` (CEPAM has no ammonia) returns None for it; the pages show `nei.context()` instead. `facility_ranks()` appends an Ammonia row.
- **Phase 7, data.** `camp/apps/emissions/wellstar.py` pages the WellSTAR REST layer (`resultOffset`, 5,000 rows a page, `orderByFields=API`), parses each feature and upserts `Well` on `api`, deleting rows no longer returned; `import_wells` runs it, a weekly `db_periodic_task` on the `primary` queue calls the command under `lock_task`. `camp/apps/emissions/wells.py` is the read side (area counts, schools near wells, the Kern callout) with its own cache generation (the dairies pattern).
- **Phase 7, the overlay.** `GET /api/2.0/emissions/wells/geojson/` returns every Valley well with properties `id, s, h` only, cached a day under the wells generation; `GET /api/2.0/emissions/wells/<sqid>/` is the popup's detail. `facility-map.js` gets a clustered `wells` source and three layers, a checkbox in the legend card, `?wells=1|0` in the URL, cluster click zooms in, well click fetches the detail. `facility_map_config(wells=...)` carries the URLs, the initial state and the page default (on for Kern County's page and the oil-gas sector page).

**Tech Stack:** Django 5 / GeoDjango + PostGIS (`dwithin` in degrees as the index prefilter, `distance_lte` with `D(ft=…)` for the exact check, as `schools.py` does), django-vanilla-views, django-resticus + `CachedEndpointMixin`, django-huey (`db_periodic_task`, `lock_task`), `requests`, stdlib `zipfile`/`csv`, MapTiler SDK (MapLibre GL: GeoJSON source clustering) on the map core (`assets/js/maps/`), Bulma, Selenium smoke script.

**Spec:** `docs/superpowers/specs/2026-09-28-emissions-data-expansion-design.md`, sections "Shared: SourceImport", "Phase 5" and "Phase 7". Research: `.superpowers/research/ammonia-ghg.md` (section 1) and `.superpowers/research/oilgas-ces-schools.md` (Part A and B6).

## Global Constraints

- **Where to work.** Worktree `/home/derek/dev/ccac/sjvair.com/.claude/worktrees/feature+ceidars-explorer` (`<worktree>` below). The phase branches are a chain: phase 1 → 2 → 3 → 4 → 6 → **5** → **7** → 8 → 9, each stacked on the previous one so migrations number sequentially (no `--merge` migrations). Part A is branch `feature/emissions-ammonia`, created from the tip of the Phase 6 branch; Part B is `feature/emissions-wells`, created from the tip of Part A. Use absolute paths and `git -C <worktree>` for every git command; never touch `/home/derek/dev/ccac/sjvair.com` (the main checkout) or another worktree. After each commit, verify it with `git -C <worktree> log --oneline -1`.
- **Plan against the code as the earlier plans leave it.** This plan reads: Phase 1's `SourceImport`, `ToxicPollutant`, `ToxicEmission`, `pollutants.Pollutant` (with `weight_field`, `pollutant_id`, `unit`/`unit_label`), `stats.value_expr` / `valued` / `values` / `prefix()` / `clear_caches()` / `toxic_options`, `Home` passing `total=totals['value']`, the picker's `pollutant_options`, `FacilityList.csv_response`'s `toxic_column`; Phase 2's `schools.near()` and the `{% if nearby is not None %}` schools card in `facility-detail.html`; Phase 3's `community-card.html` include and the section nav condition in `area.html`; Phase 4's `camp/apps/emissions/tasks.py`, `compliance_line` after the top facilities table, and `test_tasks.py`; Phase 6's `dairy-stats.html` Water Board tile and `DairyAreaPage`; the dairy region pages plan's `dairy_block`, `DairyAreaPage.get_context_data` (`carb_estimate`, `hide_county`), `RegionLookupMixin` / `NearLookupMixin`. Where a step says "after X", find X by name, not by line number. **Do not redefine `SourceImport`**: it exists (Phase 1); import it.
- **Tests** use `django.test.TestCase` with plain `assert` (never `self.assertX`), `pytest.raises` for exceptions; fixtures `regions.yaml`, `emissions.yaml`. Existing helpers: `camp/apps/emissions/tests/test_areas.py` (`make`, `AROUND_PLANT`), `test_areas_pages.py` (`map_data`), `test_stats.py` (`scope`), `test_dairies.py` (`make_dairies`, `make_dairy`, `dairy_inventory`, `IN_KERN`, `NEAR_PLANT`), `test_views.py` (`ViewTestCase`), `test_dairy_area_pages.py` (`DairyAreaTestCase`). Tests never hit the network: every fetch is behind a module-level function (`nei.download`, `wellstar.fetch_page`) that tests patch, and every sample file is a small checked-in file under `camp/apps/emissions/tests/data/`, trimmed from the real download by the commands each task gives.
- **New models use sqids:** `sqid = SqidsField(alphabet=shuffle_alphabet('emissions.<ModelName>'))` beside the integer PK. Verbose names use `_()` as the first positional argument; don't align `=`. No `SmallUUIDField`.
- **Test command** (`$TEST <paths>` below; `<db>` is `sjvair_ammonia` for Part A, `sjvair_wells` for Part B):
  `docker compose -f /home/derek/dev/ccac/sjvair.com/docker-compose.yml --project-directory /home/derek/dev/ccac/sjvair.com run --rm -T -e DATABASE_URL=postgis://sjvair:changeme@db:5432/<db> -v /home/derek/dev/ccac/sjvair.com/.claude/worktrees/feature+ceidars-explorer:/app test pytest <paths> -q -p no:cacheprovider --create-db`
  `fatal: not a git repository` in its output is harmless.
- **Management commands against the worktree** (`$MANAGE <args>` below): the same prefix without `-e`, service `web`, `python manage.py <args>`.
- **Asset rebuild** (`$ASSETS`): the same prefix without `-e`, service `web`, `invoke vendor bundle styles`. Run `node --check` on every JS file touched. Built bundle files: follow the precedent `git -C <worktree> log --stat -3 -- assets/js/emissions/facility-map.js` shows (commit them by explicit path only if the repo tracks them).
- **Smoke:** `/home/derek/.claude/jobs/d44a9b36/tmp/venv/bin/python scripts/emissions_map_smoke.py --base http://localhost:8003`. The dev server's container is `docker ps --filter publish=8003`; never stop it. It serves this worktree: after each migration run `docker exec $(docker ps --filter publish=8003 --format '{{.Names}}') python manage.py migrate`.
- **Commits:** explicit paths only (`git -C <worktree> add <new files>`, then `git -C <worktree> commit -m "…" -- <every path>`). Never `git add -A`, never `git stash`, never push, no AI attribution or Co-Authored-By trailers. Message style: `feat(emissions): …`, `test(emissions): …`, `docs(emissions): …`.
- **Deploy notes go in the PR description, not CLAUDE.md.** Tasks 3 and 8 draft them.
- **Copy, verbatim from the spec.** Phase 5 caveat paragraph (About page): "Ammonia isn't toxic at these levels, but it reacts with other pollution to form fine particles (PM2.5), the Valley's main winter air problem. Most Valley ammonia, about 90%, comes from livestock and fertilizer that aren't permitted facilities; only 7 dairies report ammonia to CARB. County figures are EPA and CARB model estimates for 2023, not measurements." Phase 7 caveat paragraph: "Well counts are CalGEM's regulatory records, not emissions. Idle wells can still leak; plugged wells aren't shown. Health-protection-zone status is CalGEM's and is still being revised. Distances to schools are straight lines from the school's map point (the law measures from property lines). Oil & gas "facilities" in CARB's inventory are permit groupings that can cover a whole field; their map points aren't well locations." Wells line: `N active · N idle · N in a verified health-protection zone (3,200 ft of homes or schools)`. Schools line: `N schools and child-care centers here have an active or idle well within 3,200 ft`. Kern sentence: `Oil & gas facilities reported P% of Kern's permitted-facility ROG and Q% of its benzene in {year}`. Facility note: `This is a district permit grouping that can span a whole oil field. Its map point is the operator's address, not a well.` Picker label `Ammonia (NH3)` is rendered as the label `NH3` with the grey name `Ammonia` (the picker's existing label + name layout).
- **Decisions made while planning** (the spec is otherwise followed as written):
  1. The picker key is `nh3`, the `Pollutant` is `Pollutant('nh3', 'NH3', 'Ammonia', carb_id='7664417')`, unit `tons`. `Pollutant.carb_id` (not a new `precursor` flag) marks it, and `Pollutant.precursor` is a property over it. It is the only member of `PRECURSORS`.
  2. The NEI bar's segments are Dairy cattle, Other livestock, Fertilizer and Everything else (EPA's sectors); permitted facilities aren't a segment (they're inside EPA's point sectors) but a sentence above the bar: what CEIDARS facilities reported in the scope year, and what share of the county's EPA total that is. The two years (the scope's, and NEI's 2023) are both named.
  3. The NEI CSVs' column names are read case-insensitively from a small set of candidates (`nei.SECTOR_COLUMNS` / `NONPOINT_COLUMNS`), and the checked-in trimmed samples carry the real headers, so `test_the_real_layout` fails if EPA's header drifts. The livestock rows come from the nonpoint file's `Agriculture - Livestock Waste` sector when it has a sector column, else from SCC level-3 names ending in "waste".
  4. Region and near-me pages get **one** "Oil & gas wells" section (`includes/wells-block.html`, `id="wells"`, in the section nav) holding the counts line, the Kern sentence (Kern County only) and the schools list, rather than a headline line plus a separate schools block; the sector page shows only the Kern sentence.
  5. The schools count uses every stored well (Active, Idle and New; plugged wells aren't imported), with the spec's copy. `wells.schools_near_wells(area)` is where the spec's `schools.wells_near_locations` lives, so Phase 2's `schools.py` is untouched.
  6. Well clusters are sized by count and coloured by their active share; they carry no count label (no map here draws text, and a symbol layer needs a glyph font the style may not serve). Clicking a cluster zooms in; clicking a well fetches `wells/<sqid>/` for the popup, so the GeoJSON stays `id, s, h`.
  7. The Kern callout's shares are over every Kern facility with a record that year, minor sources included (the research's 40.6% / 38.2% figures), and read benzene from `ToxicEmission` (CARB id 71432).
  8. Wells are matched to a county by `CountyName` + " County" against `Region.objects.counties()`; a feature whose county isn't covered (the REST `where` already limits it) or has no coordinates is skipped and counted.

## Review Focus

- **Ammonia is never a toxic and never weighted.** It appears in the criteria-side picker only (`stats.toxic_options` and `facility_toxics` still exclude `kind='precursor'`, pinned by Phase 1's tests, which must keep passing); `scope(pollutant='nh3')` is not `toxics`; its values are tons (lbs ÷ 2,000). Pinned by `PrecursorTests` (Task 2).
- **`county_context()` must return None for `nh3`** (CEPAM has no ammonia; the old code would `KeyError` on `totals(scope)['nh3']`), and the NEI bar replaces it. Pinned by `test_county_context_is_none_for_ammonia` (Task 2) and `NeiBarTests` (Task 3).
- **The NEI import streams.** `nei.read_sector` / `read_nonpoint` iterate `csv.DictReader` over `zipfile.ZipFile.open()`; nothing calls `extractall`, `read()` on a member, or `pandas`. Pinned by review of `nei.py` and by `test_reads_from_the_zip_without_extracting` (Task 1, a 2.8 GB file would otherwise be written to disk on the dyno).
- **A well no longer returned is deleted; a returned one is upserted, never duplicated.** Pinned by `test_rerun_upserts_and_removes` (Task 4).
- **The 3,200-ft school count is a true great-circle distance.** A well at 3,000 ft counts, one at 3,400 ft doesn't. Pinned by `test_schools_near_wells_boundary` (Task 5).
- **Nothing on a facility page measures from an oil-gas facility's point.** The oil-gas note replaces the schools card (Phase 2 already hides `near()` for that sector). Pinned by `test_oil_gas_note_replaces_the_schools_card` (Task 7).
- **The overlay is off unless asked.** `data-wells` is `''` on the map page, region pages and near-me by default, `'1'` on Kern County's page and the oil-gas sector page, and `?wells=` overrides both ways; a facility's own map never offers it (`data-wells-url` blank). Pinned by `OverlayConfigTests` (Task 7).

---

# Part A: Phase 5, Ammonia

### Task 1: `CountyNEI`, `nei.py` and `import_nei`

**Files:**
- Modify: `camp/apps/emissions/models.py` (append after `CountyInventory`)
- Create: `camp/apps/emissions/migrations/0013_countynei.py` (generated; use the number `makemigrations` gives)
- Modify: `camp/apps/emissions/admin.py`
- Create: `camp/apps/emissions/nei.py`
- Create: `camp/apps/emissions/management/commands/import_nei.py`
- Create: `camp/apps/emissions/tests/data/nei/sector.csv`, `camp/apps/emissions/tests/data/nei/nonpoint.csv` (trimmed real files, Step 2)
- Create: `camp/apps/emissions/tests/test_nei.py`

**Interfaces:**
- `CountyNEI(sqid, county FK, year, pollutant='NH3', sector, subsector='', tons)`; `unique (county, year, pollutant, sector, subsector)`.
- `nei.SOURCE = 'nei'`, `nei.POLLUTANT = 'NH3'`, `nei.URLS = {2023: (SECTOR_URL, NONPOINT_URL)}`, `nei.LIVESTOCK_SECTOR`, `nei.FERTILIZER_SECTOR`, `nei.DAIRY_SUBSECTOR`.
- `nei.download(url) -> str` (temp path; the one network call; tests patch it).
- `nei.read_sector(zip_path, fips) -> [{'fips', 'sector', 'tons'}]`, `nei.read_nonpoint(zip_path, fips) -> [{'fips', 'level3', 'tons'}]` (livestock rows only), both streamed and summed per key.
- `nei.apply(year, sector_rows, nonpoint_rows) -> Report` (one transaction; replaces the year; `SourceImport('nei', version=str(year))`; `stats.clear_caches()`).
- `nei.county_fips() -> {fips: Region}` for the covered counties.
- Command: `import_nei --year 2023 [--sector-path ZIP] [--nonpoint-path ZIP]`.

- [ ] **Step 1: The model, migration and admin**

Append to `camp/apps/emissions/models.py` after `CountyInventory`:

```python
class CountyNEI(models.Model):
    """
    One county's emissions of one pollutant in EPA's National Emissions
    Inventory for one NEI year, by EPA sector (subsector blank) or, for the
    livestock-waste sector, by animal type (the nonpoint file's SCC level 3,
    "Dairy Cattle Waste"). Every source, not only permitted facilities; EPA
    and CARB model estimates in tons per year, not measurements. Ammonia only
    for now: CARB's own county inventory (CEPAM) publishes none.
    """

    sqid = SqidsField(alphabet=shuffle_alphabet('emissions.CountyNEI'))
    county = models.ForeignKey('regions.Region', verbose_name=_('County'), on_delete=models.CASCADE, related_name='+')
    year = models.IntegerField(_('NEI year'))
    pollutant = models.CharField(_('Pollutant code'), max_length=8, default='NH3')
    sector = models.CharField(_('EPA sector'), max_length=128)
    subsector = models.CharField(_('Subsector'), max_length=128, blank=True)
    tons = models.FloatField(_('Emissions (tons/yr)'))

    class Meta:
        unique_together = [('county', 'year', 'pollutant', 'sector', 'subsector')]
        verbose_name = 'county NEI row'
        verbose_name_plural = 'county NEI rows'

    def __str__(self):
        return f'{self.county} {self.year} {self.pollutant} {self.sector}{" / " + self.subsector if self.subsector else ""}'
```

Run `$MANAGE makemigrations emissions --name countynei`; confirm one `CreateModel` (the file is `0013_countynei.py` if the chain is as expected; keep whatever number it got). In `camp/apps/emissions/admin.py`, add `CountyNEI` to the `.models` import and append:

```python
@admin.register(CountyNEI)
class CountyNEIAdmin(ReadOnlyAdminMixin, base_admin.ModelAdmin):
    list_display = ['county', 'year', 'pollutant', 'sector', 'subsector', 'tons']
    list_filter = ['year', 'pollutant', 'county', 'sector']
    search_fields = ['sector', 'subsector']
```

- [ ] **Step 2: Produce the checked-in samples (real rows, streamed, never unpacked)**

On the host, once, outside the container (the sector zip is 97 MB, the nonpoint zip 309 MB with a 2.8 GB CSV inside; this reads them through `zipfile` without writing the CSVs):

```bash
mkdir -p /tmp/nei && cd /tmp/nei
curl -sSLo sector.zip https://gaftp.epa.gov/air/nei/2023/data_summaries/eis_report_38706_county_Sector_allpolls_28aug26.zip
curl -sSLo nonpoint.zip https://gaftp.epa.gov/air/nei/2023/data_summaries/2023nei_nonpoint_28aug2026.zip
OUT=/home/derek/dev/ccac/sjvair.com/.claude/worktrees/feature+ceidars-explorer/camp/apps/emissions/tests/data/nei; mkdir -p "$OUT"
python3 - "$OUT" <<'EOF'
import csv, io, sys, zipfile
out = sys.argv[1]
FIPS = {'06019', '06029', '06031', '06039', '06047', '06077', '06099', '06107'}

def col(fieldnames, *words):
    """The first header containing every word (case-insensitive)."""
    for name in fieldnames:
        if all(word in name.lower() for word in words):
            return name
    raise SystemExit(f'no column with {words} in {fieldnames}')

def trim(zip_path, out_path, extra):
    with zipfile.ZipFile(zip_path) as archive:
        name = [n for n in archive.namelist() if n.lower().endswith('.csv')][0]
        reader = csv.DictReader(io.TextIOWrapper(archive.open(name), encoding='utf-8-sig', newline=''))
        fips, poll = col(reader.fieldnames, 'fips'), col(reader.fieldnames, 'pollutant', 'code')
        kept = other = 0
        with open(out_path, 'w', newline='') as handle:
            writer = csv.DictWriter(handle, fieldnames=reader.fieldnames)
            writer.writeheader()
            for row in reader:
                valley = str(row[fips]).strip().zfill(5) in FIPS
                nh3 = row[poll].strip().upper() == 'NH3'
                if valley and nh3 and extra(row):
                    writer.writerow(row); kept += 1
                elif other < 2 and (nh3 != valley):
                    # One non-Valley NH3 row and one Valley non-NH3 row: the filters have something to drop.
                    writer.writerow(row); other += 1
        print(out_path, kept, 'kept', other, 'decoys')

trim('sector.zip', f'{out}/sector.csv', lambda row: True)
# Nonpoint: only the livestock-waste rows (the file is county x SCC, every sector).
trim('nonpoint.zip', f'{out}/nonpoint.csv', lambda row: any('waste' in str(v).lower() and 'livestock' in str(v).lower() for v in row.values()) or any(str(v).strip().lower().endswith('waste') for v in row.values()))
EOF
wc -l "$OUT"/*.csv; head -1 "$OUT"/*.csv
```

Expect a few hundred rows in `sector.csv` (eight counties × EPA's ~60 sectors) and a few dozen in `nonpoint.csv`; both under 100 KB. **Read both headers now** and compare them with `nei.SECTOR_COLUMNS` / `NONPOINT_COLUMNS` in Step 3: if a real header isn't among a key's candidates, add the real spelling (lowercased) to that key's tuple. The exact sector strings matter too: `grep -i 'livestock\|fertilizer' "$OUT/sector.csv" | cut -d, -f1-4 | sort -u` and `cut` the level-3 column of `nonpoint.csv`; set `LIVESTOCK_SECTOR`, `FERTILIZER_SECTOR` and `DAIRY_SUBSECTOR` to the exact strings the files use (the research recorded "Agriculture - Livestock Waste" style names and "Dairy Cattle Waste").

- [ ] **Step 3: Write `nei.py`**

```python
"""
EPA's National Emissions Inventory (NEI) at the county level, for what
CARB's own county inventory (CEPAM) doesn't publish: ammonia. Two data
summaries per NEI year, read straight out of their zips (the nonpoint CSV is
2.8 GB unpacked; nothing here writes it to disk):

- county x EPA sector, all pollutants: every county's total by sector;
- nonpoint county x SCC: the livestock-waste sector split by animal type
  (SCC level 3: "Dairy Cattle Waste", "Beef cattle waste", ...).

Only NH3 rows for the covered counties are kept. County FIPS codes join to
the county Regions' external_id (all eight). Estimates, not measurements.
"""
import csv
import io
import tempfile
import zipfile
from dataclasses import dataclass

import requests
from django.core.cache import cache
from django.db import transaction
from django.db.models import Sum

from camp.apps.emissions import stats
from camp.apps.emissions.models import CountyNEI, SourceImport
from camp.apps.regions.models import Region

SOURCE = 'nei'
POLLUTANT = 'NH3'
LBS_PER_TON = 2000.0
SECTOR_URL = 'https://gaftp.epa.gov/air/nei/2023/data_summaries/eis_report_38706_county_Sector_allpolls_28aug26.zip'
NONPOINT_URL = 'https://gaftp.epa.gov/air/nei/2023/data_summaries/2023nei_nonpoint_28aug2026.zip'
# NEI year -> (county x sector zip, nonpoint county x SCC zip). Add a row per release.
URLS = {2023: (SECTOR_URL, NONPOINT_URL)}
# EPA's sector names as the files spell them (Step 2 checks them against the samples).
LIVESTOCK_SECTOR = 'Agriculture - Livestock Waste'
FERTILIZER_SECTOR = 'Agriculture - Fertilizer Application'
DAIRY_SUBSECTOR = 'Dairy Cattle Waste'
# Each logical column's accepted header spellings, lowercased (the header is the contract).
SECTOR_COLUMNS = {
    'fips': ('fips code', 'state and county fips code', 'fips'),
    'sector': ('sector', 'eis sector'),
    'pollutant': ('pollutant code',),
    'tons': ('total emissions',),
    'uom': ('emissions uom', 'uom'),
}
NONPOINT_COLUMNS = {
    'fips': ('fips code', 'state and county fips code', 'fips'),
    'level3': ('scc level three', 'scc level 3', 'scc level-3'),
    'pollutant': ('pollutant code',),
    'tons': ('total emissions',),
    'uom': ('emissions uom', 'uom'),
}
NONPOINT_OPTIONAL = {'sector': ('sector', 'eis sector')}
CACHE_TIMEOUT = stats.CACHE_TIMEOUT


class NEIFormatError(ValueError):
    """The zip isn't the NEI layout this importer knows: no CSV, or a column is missing."""


def download(url):
    """Fetch a zip to a temp file and return its path (the caller unlinks it). The one network call here."""
    response = requests.get(url, timeout=1800, stream=True)
    response.raise_for_status()
    with tempfile.NamedTemporaryFile(suffix='.zip', delete=False) as tmp:
        for chunk in response.iter_content(chunk_size=1 << 20):
            tmp.write(chunk)
    return tmp.name


def county_fips():
    """{5-digit county FIPS: county Region} for the covered counties (external_id is the FIPS)."""
    return {str(region.external_id).zfill(5): region for region in Region.objects.counties()}


def _resolve(fieldnames, columns, optional=None):
    """{logical name: real header} for `columns` (required) and `optional`; raises NEIFormatError on a missing required one."""
    lowered = {(name or '').strip().lower(): name for name in fieldnames or []}
    mapping = {}
    for key, candidates in columns.items():
        real = next((lowered[c] for c in candidates if c in lowered), None)
        if real is None:
            raise NEIFormatError(f"No {key} column ({' / '.join(candidates)}) in {list(lowered)}.")
        mapping[key] = real
    for key, candidates in (optional or {}).items():
        real = next((lowered[c] for c in candidates if c in lowered), None)
        if real is not None:
            mapping[key] = real
    return mapping


def _rows(zip_path, columns, optional=None):
    """Streams the zip's first CSV row by row as {logical name: value}; never extracts."""
    with zipfile.ZipFile(zip_path) as archive:
        names = [name for name in archive.namelist() if name.lower().endswith('.csv')]
        if not names:
            raise NEIFormatError(f'{zip_path} has no CSV member.')
        with archive.open(names[0]) as member:
            reader = csv.DictReader(io.TextIOWrapper(member, encoding='utf-8-sig', errors='replace', newline=''))
            mapping = _resolve(reader.fieldnames, columns, optional)
            for row in reader:
                yield {key: (row.get(real) or '').strip() for key, real in mapping.items()}


def _tons(row):
    """The row's emissions as tons/yr (the files say TON; a LB row is converted)."""
    try:
        value = float(row['tons'])
    except (TypeError, ValueError):
        return None
    if row.get('uom', '').upper().startswith('LB'):
        value /= LBS_PER_TON
    return value


def read_sector(zip_path, fips):
    """[{'fips', 'sector', 'tons'}] for NH3 in the given county FIPS codes, summed per (fips, sector)."""
    sums = {}
    for row in _rows(zip_path, SECTOR_COLUMNS):
        code = row['fips'].zfill(5)
        if row['pollutant'].upper() != POLLUTANT or code not in fips:
            continue
        tons = _tons(row)
        if tons is None:
            continue
        key = (code, row['sector'])
        sums[key] = sums.get(key, 0.0) + tons
    return [{'fips': code, 'sector': sector, 'tons': tons} for (code, sector), tons in sorted(sums.items())]


def read_nonpoint(zip_path, fips):
    """
    [{'fips', 'level3', 'tons'}] for NH3 from livestock waste in the given
    counties, summed per (fips, SCC level 3): the sector column when the
    file has one, else level-3 names ending in "waste".
    """
    sums = {}
    for row in _rows(zip_path, NONPOINT_COLUMNS, NONPOINT_OPTIONAL):
        code = row['fips'].zfill(5)
        if row['pollutant'].upper() != POLLUTANT or code not in fips:
            continue
        if 'sector' in row:
            livestock = row['sector'] == LIVESTOCK_SECTOR
        else:
            livestock = row['level3'].lower().endswith('waste')
        if not livestock:
            continue
        tons = _tons(row)
        if tons is None:
            continue
        key = (code, row['level3'])
        sums[key] = sums.get(key, 0.0) + tons
    return [{'fips': code, 'level3': level3, 'tons': tons} for (code, level3), tons in sorted(sums.items())]


@dataclass
class Report:
    year: int
    sector_rows: int = 0
    livestock_rows: int = 0
    counties: int = 0
    total_tons: float = 0.0

    def lines(self):
        return [
            f'NEI {self.year}: {self.sector_rows:,} county x sector rows and {self.livestock_rows:,} livestock rows for {self.counties} counties.',
            f'Valley {POLLUTANT}: {self.total_tons:,.0f} tons/yr.',
        ]


def apply(year, sector_rows, nonpoint_rows):
    """
    Replace the year's CountyNEI rows with the files' (one transaction),
    stamp SourceImport('nei', version=year), and orphan the cached
    explorer aggregates (the NEI bar is keyed under stats.prefix()).
    """
    counties = county_fips()
    report = Report(year=year)
    with transaction.atomic():
        CountyNEI.objects.filter(year=year, pollutant=POLLUTANT).delete()
        rows = []
        seen = set()
        for row in sector_rows:
            county = counties.get(row['fips'])
            if county is None:
                continue
            seen.add(county.pk)
            rows.append(CountyNEI(county=county, year=year, pollutant=POLLUTANT, sector=row['sector'], subsector='', tons=row['tons']))
            report.total_tons += row['tons']
        report.sector_rows = len(rows)
        for row in nonpoint_rows:
            county = counties.get(row['fips'])
            if county is None:
                continue
            rows.append(CountyNEI(county=county, year=year, pollutant=POLLUTANT, sector=LIVESTOCK_SECTOR, subsector=row['level3'], tons=row['tons']))
        report.livestock_rows = len(rows) - report.sector_rows
        report.counties = len(seen)
        CountyNEI.objects.bulk_create(rows, batch_size=1000)
        SourceImport.objects.create(
            source=SOURCE, version=str(year),
            notes={'sector_rows': report.sector_rows, 'livestock_rows': report.livestock_rows, 'counties': report.counties},
        )
    stats.clear_caches()
    return report
```

(The read side, `latest_year`, `context` and `dairy_tile`, is added in Task 3; leave room after `apply`.)

- [ ] **Step 4: The command**

`camp/apps/emissions/management/commands/import_nei.py`:

```python
import os

from django.core.management.base import BaseCommand, CommandError

from camp.apps.emissions import nei


class Command(BaseCommand):
    help = (
        "Import county ammonia (NH3) from EPA's National Emissions Inventory for the covered counties: the county x "
        'sector summary and the nonpoint livestock split. Streams both zips (never unpacked). Idempotent per year. '
        'Downloads the two zips for the year unless --sector-path / --nonpoint-path name local copies.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--year', type=int, required=True, help='NEI year (2023)')
        parser.add_argument('--sector-path', help='A downloaded county x sector "allpolls" zip')
        parser.add_argument('--nonpoint-path', help='A downloaded nonpoint county x SCC zip')

    def handle(self, *args, **options):
        year = options['year']
        sector_path = options['sector_path']
        nonpoint_path = options['nonpoint_path']
        temp = []
        try:
            if sector_path is None or nonpoint_path is None:
                if year not in nei.URLS:
                    raise CommandError(f'No download URLs for NEI {year}; pass --sector-path and --nonpoint-path (or add the year to nei.URLS).')
                sector_url, nonpoint_url = nei.URLS[year]
                if sector_path is None:
                    self.stdout.write(f'Downloading {sector_url}')
                    sector_path = nei.download(sector_url)
                    temp.append(sector_path)
                if nonpoint_path is None:
                    self.stdout.write(f'Downloading {nonpoint_url}')
                    nonpoint_path = nei.download(nonpoint_url)
                    temp.append(nonpoint_path)
            fips = set(nei.county_fips())
            try:
                self.stdout.write('Reading the county x sector summary...')
                sector_rows = nei.read_sector(sector_path, fips)
                self.stdout.write('Reading the nonpoint livestock rows (a 2.8 GB CSV; a few minutes)...')
                nonpoint_rows = nei.read_nonpoint(nonpoint_path, fips)
            except nei.NEIFormatError as err:
                raise CommandError(str(err))
        finally:
            for path in temp:
                os.unlink(path)
        if not sector_rows:
            raise CommandError('No NH3 rows for the covered counties; nothing written.')
        report = nei.apply(year, sector_rows, nonpoint_rows)
        for line in report.lines():
            self.stdout.write(line)
```

- [ ] **Step 5: Tests**

Create `camp/apps/emissions/tests/test_nei.py`:

```python
"""
data/nei/sector.csv and nonpoint.csv are trimmed from EPA's real 2023 NEI
data summaries (the county x sector "allpolls" zip and the nonpoint zip),
streamed and filtered to the Valley's NH3 rows plus two decoys; see the
Phase 5 plan, Task 1 Step 2, for the exact command.
"""
import csv
import io
import os
import tempfile
import zipfile
from pathlib import Path
from unittest.mock import patch

from django.core.cache import cache
from django.core.management import call_command
from django.test import TestCase

from camp.apps.emissions import nei, stats
from camp.apps.emissions.models import CountyNEI, SourceImport
from camp.apps.regions.models import Region

DATA = Path(__file__).parent / 'data' / 'nei'
FRESNO, KERN, LA = '06019', '06029', '06037'

SECTOR_HEADER = ['fips code', 'county', 'sector', 'pollutant code', 'total emissions', 'emissions uom']
SECTOR_ROWS = [
    [FRESNO, 'Fresno', nei.LIVESTOCK_SECTOR, 'NH3', '9784', 'TON'],
    [FRESNO, 'Fresno', nei.FERTILIZER_SECTOR, 'NH3', '3806', 'TON'],
    [FRESNO, 'Fresno', 'Waste Disposal', 'NH3', '500', 'TON'],
    [FRESNO, 'Fresno', 'Fuel Comb - Electric Generation - Natural Gas', 'NH3', '200000', 'LB'],  # 100 tons
    [FRESNO, 'Fresno', 'Mobile - On-Road non-Diesel Light Duty Vehicles', 'NOX', '5000', 'TON'],  # not NH3
    [KERN, 'Kern', nei.LIVESTOCK_SECTOR, 'NH3', '7149', 'TON'],
    [KERN, 'Kern', nei.FERTILIZER_SECTOR, 'NH3', '10255', 'TON'],
    [LA, 'Los Angeles', nei.LIVESTOCK_SECTOR, 'NH3', '999', 'TON'],  # not covered
    [FRESNO, 'Fresno', 'Waste Disposal', 'NH3', '', 'TON'],  # blank: skipped
]
NONPOINT_HEADER = ['fips code', 'county', 'sector', 'scc', 'scc level three', 'pollutant code', 'total emissions', 'emissions uom']
NONPOINT_ROWS = [
    [FRESNO, 'Fresno', nei.LIVESTOCK_SECTOR, '2805018000', nei.DAIRY_SUBSECTOR, 'NH3', '4000', 'TON'],
    [FRESNO, 'Fresno', nei.LIVESTOCK_SECTOR, '2805018001', nei.DAIRY_SUBSECTOR, 'NH3', '70', 'TON'],  # a second SCC: summed
    [FRESNO, 'Fresno', nei.LIVESTOCK_SECTOR, '2805002000', 'Beef cattle waste', 'NH3', '5714', 'TON'],
    [FRESNO, 'Fresno', nei.FERTILIZER_SECTOR, '2801700001', 'Fertilizer Application', 'NH3', '3806', 'TON'],  # not livestock
    [KERN, 'Kern', nei.LIVESTOCK_SECTOR, '2805018000', nei.DAIRY_SUBSECTOR, 'NH3', '3492', 'TON'],
    [LA, 'Los Angeles', nei.LIVESTOCK_SECTOR, '2805018000', nei.DAIRY_SUBSECTOR, 'NH3', '1', 'TON'],
]


def build_zip(directory, name, header, rows):
    """A one-CSV zip like EPA's, from a header and rows."""
    path = os.path.join(directory, name)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    writer.writerows(rows)
    with zipfile.ZipFile(path, 'w') as archive:
        archive.writestr(name.replace('.zip', '.csv'), buffer.getvalue())
    return path


def zip_of(directory, csv_path):
    """One of the checked-in trimmed CSVs, zipped the way EPA ships it."""
    path = os.path.join(directory, csv_path.stem + '-real.zip')
    with zipfile.ZipFile(path, 'w') as archive:
        archive.write(csv_path, csv_path.name)
    return path


class NEITestCase(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        cache.clear()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.fresno = Region.objects.get(type=Region.Type.COUNTY, slug='fresno')
        self.kern = Region.objects.get(type=Region.Type.COUNTY, slug='kern')
        self.sector_zip = build_zip(self.tmp.name, 'sector.zip', SECTOR_HEADER, SECTOR_ROWS)
        self.nonpoint_zip = build_zip(self.tmp.name, 'nonpoint.zip', NONPOINT_HEADER, NONPOINT_ROWS)
        self.fips = set(nei.county_fips())


class ReadTests(NEITestCase):
    def test_county_fips(self):
        assert self.fips == {'06019', '06029', '06031', '06039', '06047', '06077', '06099', '06107'}
        assert nei.county_fips()['06019'] == self.fresno

    def test_sector_rows_filter_convert_and_sum(self):
        rows = nei.read_sector(self.sector_zip, self.fips)
        by_key = {(row['fips'], row['sector']): row['tons'] for row in rows}
        assert by_key[(FRESNO, nei.LIVESTOCK_SECTOR)] == 9784
        assert by_key[(FRESNO, 'Fuel Comb - Electric Generation - Natural Gas')] == 100  # LB -> tons
        assert by_key[(FRESNO, 'Waste Disposal')] == 500  # the blank row added nothing
        assert (KERN, nei.FERTILIZER_SECTOR) in by_key
        assert not any(fips == LA for fips, _ in by_key)
        assert not any('NOX' in sector for _, sector in by_key)

    def test_nonpoint_keeps_livestock_only_and_sums_sccs(self):
        rows = nei.read_nonpoint(self.nonpoint_zip, self.fips)
        by_key = {(row['fips'], row['level3']): row['tons'] for row in rows}
        assert by_key == {
            (FRESNO, nei.DAIRY_SUBSECTOR): 4070, (FRESNO, 'Beef cattle waste'): 5714, (KERN, nei.DAIRY_SUBSECTOR): 3492,
        }

    def test_nonpoint_without_a_sector_column_uses_the_level3_name(self):
        header = [name for name in NONPOINT_HEADER if name != 'sector']
        rows = [[value for name, value in zip(NONPOINT_HEADER, row) if name != 'sector'] for row in NONPOINT_ROWS]
        path = build_zip(self.tmp.name, 'nosector.zip', header, rows)
        by_key = {(row['fips'], row['level3']) for row in nei.read_nonpoint(path, self.fips)}
        assert by_key == {(FRESNO, nei.DAIRY_SUBSECTOR), (FRESNO, 'Beef cattle waste'), (KERN, nei.DAIRY_SUBSECTOR)}

    def test_missing_column_is_a_format_error(self):
        import pytest
        path = build_zip(self.tmp.name, 'bad.zip', ['fips code', 'sector', 'value'], [[FRESNO, 'x', '1']])
        with pytest.raises(nei.NEIFormatError, match='pollutant'):
            nei.read_sector(path, self.fips)

    def test_reads_from_the_zip_without_extracting(self):
        # Nothing but the zips may appear in the temp directory: the 2.8 GB CSV must never touch the disk.
        before = set(os.listdir(self.tmp.name))
        nei.read_sector(self.sector_zip, self.fips)
        nei.read_nonpoint(self.nonpoint_zip, self.fips)
        assert set(os.listdir(self.tmp.name)) == before

    def test_the_real_layout(self):
        # The checked-in files carry EPA's real headers and sector names.
        rows = nei.read_sector(zip_of(self.tmp.name, DATA / 'sector.csv'), self.fips)
        sectors = {row['sector'] for row in rows}
        assert nei.LIVESTOCK_SECTOR in sectors and nei.FERTILIZER_SECTOR in sectors
        assert {row['fips'] for row in rows} <= self.fips and len({row['fips'] for row in rows}) == 8
        livestock = nei.read_nonpoint(zip_of(self.tmp.name, DATA / 'nonpoint.csv'), self.fips)
        assert nei.DAIRY_SUBSECTOR in {row['level3'] for row in livestock}
        assert all(row['tons'] > 0 for row in livestock)


class ApplyTests(NEITestCase):
    def run_apply(self):
        return nei.apply(2023, nei.read_sector(self.sector_zip, self.fips), nei.read_nonpoint(self.nonpoint_zip, self.fips))

    def test_writes_sector_and_subsector_rows(self):
        report = self.run_apply()
        fresno = CountyNEI.objects.filter(county=self.fresno, year=2023)
        assert fresno.filter(subsector='').count() == 4
        assert fresno.get(sector=nei.LIVESTOCK_SECTOR, subsector=nei.DAIRY_SUBSECTOR).tons == 4070
        assert fresno.get(sector=nei.LIVESTOCK_SECTOR, subsector='Beef cattle waste').tons == 5714
        assert CountyNEI.objects.filter(county=self.kern, subsector='').count() == 2
        assert not CountyNEI.objects.exclude(county__in=[self.fresno, self.kern]).exists()
        assert (report.sector_rows, report.livestock_rows, report.counties) == (6, 3, 2)
        assert abs(report.total_tons - (9784 + 3806 + 500 + 100 + 7149 + 10255)) < 1e-6
        stamp = SourceImport.latest('nei')
        assert stamp.version == '2023' and stamp.notes['counties'] == 2

    def test_rerun_replaces_and_bumps_the_cache(self):
        self.run_apply()
        before = stats.generation()
        CountyNEI.objects.filter(subsector='Beef cattle waste').update(tons=1)
        self.run_apply()
        assert CountyNEI.objects.get(county=self.fresno, subsector='Beef cattle waste').tons == 5714
        assert CountyNEI.objects.filter(year=2023).count() == 9
        assert stats.generation() == before + 1


class CommandTests(NEITestCase):
    def test_paths(self):
        call_command('import_nei', year=2023, sector_path=self.sector_zip, nonpoint_path=self.nonpoint_zip)
        assert CountyNEI.objects.count() == 9

    def test_default_downloads_and_unlinks(self):
        with patch('camp.apps.emissions.nei.download', side_effect=[self.sector_zip, self.nonpoint_zip]) as download:
            call_command('import_nei', year=2023)
        assert [c.args[0] for c in download.call_args_list] == list(nei.URLS[2023])
        assert not os.path.exists(self.sector_zip) and not os.path.exists(self.nonpoint_zip)
        assert SourceImport.latest('nei') is not None

    def test_unknown_year_without_paths(self):
        import pytest
        from django.core.management.base import CommandError
        with pytest.raises(CommandError, match='No download URLs'):
            call_command('import_nei', year=2020)
```

If the real header in `sector.csv` spells a column outside the candidates, `test_the_real_layout` says which: add the real spelling to `nei.SECTOR_COLUMNS` (never edit the sample). Run:

```
$TEST camp/apps/emissions/tests/test_nei.py camp/apps/emissions/tests/test_models.py
```

Also `$MANAGE makemigrations --check --dry-run` → "No changes detected".

- [ ] **Step 6: Load the dev server and commit**

Copy the two zips into the container (`docker cp /tmp/nei/sector.zip $(docker ps --filter publish=8003 --format '{{.Names}}'):/tmp/` and the nonpoint one), migrate, then `docker exec … python manage.py import_nei --year 2023 --sector-path /tmp/sector.zip --nonpoint-path /tmp/nonpoint.zip` (a few minutes). Expect eight counties and a Valley total near 123,000 tons.

```
git -C <worktree> add camp/apps/emissions/migrations/0013_countynei.py camp/apps/emissions/nei.py camp/apps/emissions/management/commands/import_nei.py camp/apps/emissions/tests/data/nei camp/apps/emissions/tests/test_nei.py
git -C <worktree> commit -m "feat(emissions): county ammonia from EPA's National Emissions Inventory (CountyNEI, import_nei)" -- camp/apps/emissions/models.py camp/apps/emissions/migrations/0013_countynei.py camp/apps/emissions/admin.py camp/apps/emissions/nei.py camp/apps/emissions/management/commands/import_nei.py camp/apps/emissions/tests/data/nei camp/apps/emissions/tests/test_nei.py
```

---

### Task 2: Ammonia as an explorer pollutant

**Files:**
- Modify: `camp/apps/emissions/pollutants.py` (`Pollutant`, `NH3`, `PRECURSORS`, `POLLUTANTS`)
- Modify: `camp/apps/emissions/stats.py` (`value_expr`, `county_context`, `facility_ranks`, new `precursor_row`)
- Modify: `camp/apps/emissions/views.py` (`ScopeMixin.get_context_data`, `FacilityList.csv_response`)
- Modify: `camp/templates/emissions/includes/scope-picker.html`
- Test: `camp/apps/emissions/tests/test_stats.py`, `test_views.py`, `test_facility_page.py`, `camp/api/v2/emissions/tests.py`

**Interfaces:**
- `pollutants.Pollutant(key, label, name, toxic=False, weight_field='', pollutant_id=None, carb_id='')`; property `precursor -> bool(carb_id)`; `unit` stays `'tons'` for it.
- `pollutants.LBS_PER_TON = 2000.0`, `pollutants.NH3`, `pollutants.PRECURSORS = [NH3]`; `POLLUTANTS` includes it; `get_pollutant('nh3')` returns it.
- `stats.value_expr(pollutant)` returns, for a precursor, that facility-year's `ToxicEmission.lbs` for `carb_id` ÷ 2,000 as a float.
- `stats.county_context(scope)` returns None for a precursor.
- `stats.precursor_row(facility, year, pollutant=NH3) -> dict | None` (a `facility_ranks()` row); `facility_ranks()` appends it when the facility reported ammonia.
- Context `pollutant_options` on the criteria side is `CRITERIA + PRECURSORS`.

- [ ] **Step 1: Write the failing tests**

Append to `camp/apps/emissions/tests/test_stats.py` (import `NH3, PRECURSORS` from `camp.apps.emissions.pollutants` beside its existing imports):

```python
class PrecursorTests(StatsTestCase):
    def test_nh3_is_a_criteria_side_pollutant_in_tons(self):
        assert NH3.key == 'nh3' and NH3.precursor and not NH3.toxic and not NH3.weighted
        assert NH3.unit == 'tons' and NH3.unit_label == 'tons/yr'
        assert get_pollutant('nh3') is NH3 and PRECURSORS == [NH3]
        s = scope(pollutant='nh3')
        assert s.pollutant is NH3 and not s.toxics
        assert s.query() == '?pollutant=nh3'
        assert scope(toxics=1, pollutant='nh3').pollutant.key == 'cancer'  # never a toxic

    def test_values_are_lbs_over_2000(self):
        # The fixture: TEST PLANT reported 100 lbs of ammonia in 2024; nobody else reported any.
        s = scope(pollutant='nh3')
        assert dict(stats.values(s)) == {self.plant.pk: 0.05, self.cement.pk: None}
        assert stats.totals(s)['value'] == 0.05
        assert stats.ranks(s) == {self.plant.pk: 1}
        assert [r.facility.name for r in stats.facility_table(s)] == ['TEST PLANT', 'TEST CEMENT']
        assert stats.by_year(s, facility=self.plant) == [{'year': 2023, 'value': 0.0}, {'year': 2024, 'value': 0.05}]
        sectors = {row['sector']: row['value'] for row in stats.sector_breakdown(s)}
        assert sectors['glass'] == 0.05 and sectors['cement-minerals'] == 0.0

    def test_county_context_is_none_for_ammonia(self):
        CountyInventory.objects.create(county=self.fresno, year=2024, inventory=cepam.INVENTORY, source_type='mobile', eic='723', nox=1.0)
        assert stats.county_context(scope(pollutant='nox', county='fresno')) is not None
        assert stats.county_context(scope(pollutant='nh3', county='fresno')) is None

    def test_facility_ranks_append_an_ammonia_row(self):
        rows = stats.facility_ranks(self.plant, 2024)
        assert [row['pollutant'].key for row in rows] == ['nox', 'rog', 'pm', 'pm10', 'sox', 'co', 'tog', 'nh3']
        nh3 = rows[-1]
        assert nh3['value'] == 0.05 and (nh3['county_rank'], nh3['county_count']) == (1, 1)
        assert (nh3['sector_rank'], nh3['sector_count']) == (1, 1) and nh3['county_share'] == 1.0
        assert [row['pollutant'].key for row in stats.facility_ranks(self.cement, 2024)][-1] == 'tog'
        assert stats.precursor_row(self.cement, 2024) is None
```

Append to `camp/apps/emissions/tests/test_views.py` (class `HomeTests`' `test_renders_for_every_scope` params list gains `{'pollutant': 'nh3'}` and `{'pollutant': 'nh3', 'county': 'fresno'}`), and a new class:

```python
class AmmoniaPagesTests(ViewTestCase):
    def test_picker_lists_ammonia_under_a_precursor_heading(self):
        content = self.get('home').content.decode()
        assert 'pollutant=nh3' in content and 'pollutant=nh3' not in self.get('home', params={'toxics': 1}).content.decode()
        heading = content.index('explorer-scope-group">Precursor')
        assert content.index('pollutant=tog') < heading < content.index('pollutant=nh3')
        assert '<span class="has-text-grey">Ammonia</span>' in content

    def test_ammonia_scope_pages(self):
        content = self.get('home', params={'pollutant': 'nh3'}).content.decode()
        assert '<span class="explorer-scope-label">NH3</span>' in content and 'tons/yr' in content
        assert 'CARB estimates all sources' not in content  # CEPAM has no ammonia
        self.get('map', params={'pollutant': 'nh3'})
        self.get('sector-detail', 'glass', params={'pollutant': 'nh3'})
        content = self.get('facility-list', params={'pollutant': 'nh3'}).content.decode()
        assert 'NH3 (tons/yr)' in content

    def test_csv_carries_an_nh3_tons_column(self):
        rows = list(csv.DictReader(io.StringIO(self.get('facility-list', params={'format': 'csv', 'pollutant': 'nh3'}).content.decode())))
        assert float(rows[0]['nh3_tons']) == 0.05 and rows[0]['facility'] == 'TEST PLANT'
        assert 'nh3_tons' not in list(csv.DictReader(io.StringIO(self.get('facility-list', params={'format': 'csv'}).content.decode())))[0]
```

Append to `camp/apps/emissions/tests/test_facility_page.py`:

```python
class FacilityAmmoniaRowTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        cache.clear()

    def test_ammonia_row_in_the_emissions_table(self):
        content = self.client.get(Facility.objects.get(name='TEST PLANT').get_absolute_url()).content.decode()
        table = content[content.index('Emissions in 2024'):content.index('Toxic air contaminants in 2024')]
        assert 'pollutant=nh3' in table and 'Ammonia' in table
        assert table.index('TOG') < table.index('Ammonia')
        content = self.client.get(Facility.objects.get(name='TEST CEMENT').get_absolute_url()).content.decode()
        assert 'pollutant=nh3' not in content
```

Append to `camp/api/v2/emissions/tests.py`, class `FacilityGeoJSONTests`:

```python
    def test_ammonia_in_tons(self):
        body = self.client.get(reverse('api:v2:emissions:geojson'), {'pollutant': 'nh3'}).json()
        assert body['properties']['pollutant'] == 'nh3' and body['properties']['unit'] == 'tons'
        values = {f['properties']['name']: f['properties']['value'] for f in body['features']}
        assert values['TEST PLANT'] == 0.05 and values['TEST CEMENT'] is None
```

- [ ] **Step 2: Run them and watch them fail**

`$TEST camp/apps/emissions/tests/test_stats.py::PrecursorTests camp/apps/emissions/tests/test_views.py::AmmoniaPagesTests` — `ImportError: cannot import name 'NH3'`.

- [ ] **Step 3: `pollutants.py`**

In the `Pollutant` dataclass add the field and property (after `pollutant_id`):

```python
    carb_id: str = ''  # a precursor CARB delivers in its toxics feed (ammonia): read from ToxicEmission, shown in tons

    @property
    def precursor(self):
        return bool(self.carb_id)
```

`unit` needs no change (`toxic=False` → `'tons'`). After `CRITERIA`, add:

```python
LBS_PER_TON = 2000.0

# Ammonia: a PM2.5 precursor (winter ammonium nitrate), not a toxic. CARB
# delivers it in the toxics feed (ToxicEmission, kind 'precursor', CARB id
# 7664417); the explorer shows it beside the criteria pollutants, in tons/yr.
NH3 = Pollutant('nh3', 'NH3', 'Ammonia', carb_id='7664417')
PRECURSORS = [NH3]
```

and make `POLLUTANTS = {pollutant.key: pollutant for pollutant in CRITERIA + PRECURSORS + WEIGHTED}`. `get_pollutant` needs no change (it returns any non-toxic key it knows). Update the module docstring: "the criteria pollutants, ammonia (a precursor), the two weighted toxics measures…".

- [ ] **Step 4: `stats.py`**

Imports: add `LBS_PER_TON, NH3, PRECURSORS` to the `pollutants` import. In `value_expr`, before `if not pollutant.toxic:`:

```python
    if pollutant.precursor:
        rows = ToxicEmission.objects.filter(
            facility_id=OuterRef('facility_id'), year=OuterRef('year'), pollutant__carb_id=pollutant.carb_id,
        )
        lbs = Cast(Subquery(rows.values('lbs')[:1]), FloatField())
        return ExpressionWrapper(lbs / Value(LBS_PER_TON), output_field=FloatField())
```

and extend its docstring: "for a precursor (ammonia), that facility-year's pounds ÷ 2,000". In `county_context`, the guard becomes `if scope.toxics or scope.pollutant.precursor or scope.year is None:` and the docstring says "None for toxics and ammonia (CEPAM has neither)". After `facility_ranks`, add:

```python
def precursor_row(facility, year, pollutant=NH3):
    """
    facility_ranks()'s row for ammonia: the facility's tons that year (its
    ToxicEmission pounds ÷ 2,000) ranked among its county's and its sector's
    facilities that reported any, on the same minor-source rule; None when it
    reported none.
    """
    rows = ToxicEmission.objects.filter(year=year, pollutant__carb_id=pollutant.carb_id)
    mine = rows.filter(facility=facility).values_list('lbs', flat=True).first()
    if not mine:
        return None
    peers = rows
    if not facility.is_minor_source:
        peers = peers.exclude(facility__sic_code__in=MINOR_SOURCE_SIC_CODES)
    to_tons = lambda values: [float(v) / LBS_PER_TON for v in values if v]
    county_values = to_tons(peers.filter(facility__county_id=facility.county_id).values_list('lbs', flat=True))
    sector_values = to_tons(peers.filter(facility__sector=facility.sector).values_list('lbs', flat=True))
    value = float(mine) / LBS_PER_TON
    county_total = sum(county_values)
    return {
        'pollutant': pollutant, 'value': value,
        'county_rank': _rank_of(value, county_values), 'county_count': len(county_values),
        'sector_rank': _rank_of(value, sector_values), 'sector_count': len(sector_values),
        'county_share': value / county_total if county_total else None,
    }
```

and at the end of `facility_ranks`, before `return result`:

```python
    for pollutant in PRECURSORS:
        row = precursor_row(facility, year, pollutant)
        if row is not None:
            result.append(row)
```

(`facility_ranks` returns `[]` early when the facility has no record that year; a precursor row without a record is impossible in CEIDARS, so that's fine.) Update the module docstring's unit sentence to mention ammonia in tons/yr from `ToxicEmission`.

- [ ] **Step 5: The picker and the CSV**

`views.py`: import `PRECURSORS` beside `CRITERIA`; in `ScopeMixin.get_context_data`, `'pollutant_options': stats.toxic_options(scope.year) if scope.toxics else CRITERIA + PRECURSORS`. In `FacilityList.csv_response`, replace Phase 1's `toxic_column` line with:

```python
        # One extra column for a pollutant that isn't a criteria column: a
        # toxic (lbs or share) or ammonia (tons), the scope's `value`.
        criteria_keys = {pollutant.key for pollutant in CRITERIA}
        extra_column = [] if scope.pollutant.key in criteria_keys else [
            f"{scope.pollutant.key}_{'share' if scope.pollutant.weighted else scope.pollutant.unit}"
        ]
```

use `+ extra_column` in the header and `+ ([record.value] if extra_column else [])` in each row (replacing the `if scope.toxics` condition).

`includes/scope-picker.html`, inside `{% for option in pollutant_options %}`, before `{% if option.key in disabled_pollutants %}`:

```django
                {% if option.precursor %}<hr class="dropdown-divider"><span class="dropdown-item explorer-scope-group">Precursor</span>{% endif %}
```

(`Pollutant` objects on the toxics side have `precursor == False`, so the toxics picker is unchanged; the dairy pages pass `CRITERIA`, so they don't list it.) In `assets/sass/sjvair/pages/emissions.sass`, beside the `.explorer-scope-picker` rules (grep `explorer-scope-label`), add:

```sass
  .explorer-scope-group
    font-size: 0.7rem
    text-transform: uppercase
    letter-spacing: 0.05em
    color: $grey
    pointer-events: none
```

(If `$grey` isn't in scope in that file, use the literal the neighbouring rules use.) Then `$ASSETS`.

- [ ] **Step 6: Run the tests**

`$TEST camp/apps/emissions/tests/test_stats.py camp/apps/emissions/tests/test_views.py camp/apps/emissions/tests/test_facility_page.py camp/apps/emissions/tests/test_lists.py camp/apps/emissions/tests/test_areas.py camp/apps/emissions/tests/test_dairies_pages.py camp/api/v2/emissions/tests.py` — all pass (the dairy pages fall back from `nh3` to ROG with a note, through `dairies.resolve_scope`'s existing branch; nothing to change there).

- [ ] **Step 7: Commit**

```
git -C <worktree> commit -m "feat(emissions): ammonia joins the picker as a precursor, in tons/yr" -- camp/apps/emissions/pollutants.py camp/apps/emissions/stats.py camp/apps/emissions/views.py camp/templates/emissions/includes/scope-picker.html assets/sass/sjvair/pages/emissions.sass camp/apps/emissions/tests/test_stats.py camp/apps/emissions/tests/test_views.py camp/apps/emissions/tests/test_facility_page.py camp/api/v2/emissions/tests.py
```

---

### Task 3: The NEI ammonia bar, the dairy tile, About, and Part A's notes

**Files:**
- Modify: `camp/apps/emissions/nei.py` (append the read side)
- Modify: `camp/apps/emissions/views.py` (`Home`, `RegionPage.get_context_data`, `About`)
- Modify: `camp/apps/emissions/dairy_views.py` (`DairyAreaPage.get_context_data`)
- Create: `camp/templates/emissions/includes/nei-context-bar.html`
- Modify: `camp/templates/emissions/home.html`, `area.html`, `includes/dairy-stats.html`, `about.html`
- Modify: `assets/sass/sjvair/pages/emissions.sass`, `datafiles/data-integrations.yaml`
- Test: `camp/apps/emissions/tests/test_nei.py` (append), `camp/apps/emissions/tests/test_dairy_area_pages.py` (append)

**Interfaces:**
- `nei.latest_year() -> int | None` (cached under `stats.prefix()`).
- `nei.context(scope) -> dict | None`: for a precursor scope with NEI rows for its counties: `{'year', 'total', 'facilities', 'facility_share', 'parts': [{'key', 'label', 'tons', 'share'}], 'counties'}`; keys `dairy`, `livestock`, `fertilizer`, `other`.
- `nei.dairy_tile(county) -> dict | None`: `{'tons', 'share', 'year'}` for the county's dairy-cattle ammonia and its share of the county total.
- Context: `nei_context` on the home page and county region pages; `nei_dairy` on county dairy pages; `nei_stamp` on About.

- [ ] **Step 1: Write the failing tests**

Append to `test_nei.py`:

```python
class ReadSideTests(NEITestCase):
    def setUp(self):
        super().setUp()
        nei.apply(2023, nei.read_sector(self.sector_zip, self.fips), nei.read_nonpoint(self.nonpoint_zip, self.fips))
        cache.clear()

    def test_context_for_a_county(self):
        from camp.apps.emissions.tests.test_stats import scope
        context = nei.context(scope(pollutant='nh3', county='fresno'))
        assert context['year'] == 2023 and context['total'] == 9784 + 3806 + 500 + 100
        parts = {part['key']: part for part in context['parts']}
        assert [part['key'] for part in context['parts']] == ['dairy', 'livestock', 'fertilizer', 'other']
        assert parts['dairy']['tons'] == 4070 and parts['livestock']['tons'] == 9784 - 4070
        assert parts['fertilizer']['tons'] == 3806 and parts['other']['tons'] == 600
        assert abs(sum(part['share'] for part in context['parts']) - 1) < 1e-9
        # TEST PLANT's 100 lbs (0.05 tons) of CEIDARS ammonia against the county's EPA total.
        assert context['facilities'] == 0.05 and abs(context['facility_share'] - 0.05 / 14190) < 1e-12
        assert context['counties'] == [self.fresno]

    def test_context_for_the_valley_and_its_absences(self):
        from camp.apps.emissions.tests.test_stats import scope
        everywhere = nei.context(scope(pollutant='nh3'))
        assert everywhere['total'] == 14190 + 7149 + 10255 and len(everywhere['counties']) == 8
        assert nei.context(scope(pollutant='nox', county='fresno')) is None
        assert nei.context(scope(pollutant='nh3', county='tulare')) is None  # no rows for Tulare
        CountyNEI.objects.all().delete()
        stats.clear_caches()
        assert nei.context(scope(pollutant='nh3')) is None and nei.latest_year() is None

    def test_dairy_tile(self):
        tile = nei.dairy_tile(self.fresno)
        assert tile == {'tons': 4070, 'share': 4070 / 14190, 'year': 2023}
        assert nei.dairy_tile(self.kern) == {'tons': 3492, 'share': 3492 / (7149 + 10255), 'year': 2023}
        assert nei.dairy_tile(Region.objects.get(type=Region.Type.COUNTY, slug='tulare')) is None


class NeiBarTests(NEITestCase):
    def setUp(self):
        super().setUp()
        nei.apply(2023, nei.read_sector(self.sector_zip, self.fips), nei.read_nonpoint(self.nonpoint_zip, self.fips))
        cache.clear()

    def test_county_page_shows_the_bar_for_ammonia_only(self):
        content = self.client.get(self.fresno.get_emissions_url(), {'pollutant': 'nh3', 'year': '2024'}).content.decode()
        assert 'nei-context' in content and 'Dairy cattle' in content and "EPA's 2023 National Emissions Inventory" in content
        assert '14,190' in content and 'about 0%' not in content  # the share is written with `percent`: '<1%'
        assert '<1%' in content
        assert 'CARB estimates all sources' not in content
        content = self.client.get(self.fresno.get_emissions_url(), {'year': '2024'}).content.decode()
        assert 'nei-context' not in content

    def test_home_page_bar_and_a_county_without_rows(self):
        from django.urls import reverse
        content = self.client.get(reverse('emissions:home'), {'pollutant': 'nh3'}).content.decode()
        assert 'nei-context' in content and 'these counties' in content
        tulare = Region.objects.get(type=Region.Type.COUNTY, slug='tulare')
        assert 'nei-context' not in self.client.get(tulare.get_emissions_url(), {'pollutant': 'nh3'}).content.decode()

    def test_about_page(self):
        from django.urls import reverse
        content = self.client.get(reverse('emissions:about')).content.decode()
        assert '<h2 id="ammonia">Ammonia</h2>' in content
        assert 'only 7 dairies report ammonia to CARB' in content and 'NEI 2023 loaded' in content
        assert 'National Emissions Inventory' in self.client.get('/about/integrations/').content.decode()
```

Append to `camp/apps/emissions/tests/test_dairy_area_pages.py`, class `ContentTests`:

```python
    def test_county_dairy_page_has_the_epa_ammonia_tile(self):
        from camp.apps.emissions import nei
        from camp.apps.emissions.models import CountyNEI
        CountyNEI.objects.create(county=self.fresno, year=2023, sector=nei.LIVESTOCK_SECTOR, tons=8000)
        CountyNEI.objects.create(county=self.fresno, year=2023, sector=nei.FERTILIZER_SECTOR, tons=2000)
        CountyNEI.objects.create(county=self.fresno, year=2023, sector=nei.LIVESTOCK_SECTOR, subsector=nei.DAIRY_SUBSECTOR, tons=4000)
        content = self.get(self.fresno, {'year': '2023'}).content.decode()
        assert '<p class="heading">Ammonia, EPA estimate</p><p class="title">4,000 <span class="is-size-5">tons/yr</span></p>' in content
        assert 'dairy cattle, 40% of the county&#x27;s ammonia (2023)' in content or "dairy cattle, 40% of the county's ammonia (2023)" in content
        # Not on a city's dairy page, and not without rows.
        assert 'Ammonia, EPA estimate' not in self.get(self.fresno_city, {'year': '2023'}).content.decode()
        assert 'Ammonia, EPA estimate' not in self.get(self.kern, {'year': '2023'}).content.decode()
```

- [ ] **Step 2: Run them and watch them fail**

`$TEST camp/apps/emissions/tests/test_nei.py camp/apps/emissions/tests/test_dairy_area_pages.py` — `AttributeError: module … has no attribute 'context'`.

- [ ] **Step 3: The read side of `nei.py`**

Append to `nei.py`:

```python
PARTS = (
    ('dairy', 'Dairy cattle'),
    ('livestock', 'Other livestock'),
    ('fertilizer', 'Fertilizer'),
    ('other', 'Everything else'),
)


def latest_year():
    """The newest NEI year with rows, or None before any import."""
    def compute():
        return CountyNEI.objects.filter(pollutant=POLLUTANT).order_by('-year').values_list('year', flat=True).first()
    return cache.get_or_set(f'{stats.prefix()}:nei:latest-year', compute, CACHE_TIMEOUT)


def _sums(counties, year):
    """(total, livestock, dairy, fertilizer) tons for the counties in the NEI year; total 0 when there are no rows."""
    rows = CountyNEI.objects.filter(county__in=counties, year=year, pollutant=POLLUTANT)
    total = rows.filter(subsector='').aggregate(t=Sum('tons'))['t'] or 0.0
    livestock = rows.filter(subsector='', sector=LIVESTOCK_SECTOR).aggregate(t=Sum('tons'))['t'] or 0.0
    dairy = rows.filter(sector=LIVESTOCK_SECTOR, subsector=DAIRY_SUBSECTOR).aggregate(t=Sum('tons'))['t'] or 0.0
    fertilizer = rows.filter(subsector='', sector=FERTILIZER_SECTOR).aggregate(t=Sum('tons'))['t'] or 0.0
    return total, livestock, dairy, fertilizer


def context(scope):
    """
    The all-sources ammonia bar for a precursor scope: EPA's county totals by
    source (dairy cattle, other livestock, fertilizer, everything else) beside
    what the scope's permitted facilities reported to CARB. None for any
    other pollutant, or when NEI has no rows for the scope's counties.
    """
    if not scope.pollutant.precursor or scope.year is None:
        return None

    def compute():
        year = latest_year()
        if year is None:
            return None
        counties = [scope.county] if scope.county else list(Region.objects.counties())
        total, livestock, dairy, fertilizer = _sums(counties, year)
        if not total:
            return None
        tons = {'dairy': dairy, 'livestock': livestock - dairy, 'fertilizer': fertilizer, 'other': total - livestock - fertilizer}
        facilities = stats.totals(scope)['value'] or 0.0
        return {
            'year': year,
            'total': total,
            'facilities': facilities,
            'facility_share': facilities / total,
            'parts': [{'key': key, 'label': label, 'tons': tons[key], 'share': tons[key] / total} for key, label in PARTS],
            'counties': counties,
        }
    return cache.get_or_set(scope.key('nei-context'), compute, CACHE_TIMEOUT)


def dairy_tile(county):
    """EPA's dairy-cattle ammonia for a county, {tons, share (of the county's total), year}, or None without rows."""
    def compute():
        year = latest_year()
        if year is None:
            return None
        total, _, dairy, _ = _sums([county], year)
        if not total or not dairy:
            return None
        return {'tons': dairy, 'share': dairy / total, 'year': year}
    return cache.get_or_set(f'{stats.prefix()}:nei:dairy-tile:{county.pk}', compute, CACHE_TIMEOUT)
```

- [ ] **Step 4: Views, templates, styles**

`views.py`: `from camp.apps.emissions import areas, dairies, nei, stats` (keep whatever else the earlier phases import there). `Home.get_context_data`: add `nei_context=nei.context(scope)`. `RegionPage.get_context_data`: where it builds `context_bar=stats.county_context(...) if region.type == Region.Type.COUNTY else None`, compute the county scope once and pass both:

```python
        county_scope = stats.Scope(year=self.get_scope().year, county=region, pollutant=self.get_scope().pollutant, minor=self.get_scope().minor) if region.type == Region.Type.COUNTY else None
        ...
            context_bar=stats.county_context(county_scope) if county_scope else None,
            nei_context=nei.context(county_scope) if county_scope else None,
```

`About.get_context_data`: add `nei_stamp=SourceImport.latest(nei.SOURCE)` (import `SourceImport` if the file doesn't already).

`dairy_views.py`: import `nei`; in `DairyAreaPage.get_context_data` pass `nei_dairy=nei.dairy_tile(county) if county is not None else None`.

Create `camp/templates/emissions/includes/nei-context-bar.html`:

```django
{% load emissions_explorer %}
{% comment %}
The all-sources ammonia bar (nei.context) for the NH3 scope, on the home page
and county pages in place of the CEPAM bar (CARB's county inventory has no
ammonia). EPA's NEI county estimate by source, with what the scope's permitted
facilities reported to CARB above it. Context: `nei_context`, `pollutant`, `year`, `county`.
{% endcomment %}
<div class="box emissions-context nei-context">
    <p>Permitted facilities reported about <strong>{{ nei_context.facilities|amount:pollutant }} tons</strong> of ammonia to CARB in {{ year }}.
       EPA's {{ nei_context.year }} National Emissions Inventory estimates all sources in {% if county %}{{ county.name }}{% else %}these counties{% endif %} emit about
       <strong>{{ nei_context.total|amount:pollutant }} tons</strong> a year, so permitted facilities are about {{ nei_context.facility_share|percent }} of it; most is livestock and fertilizer.</p>
    <div class="emissions-context-bar" role="img" aria-label="{% for part in nei_context.parts %}{{ part.label }} {{ part.share|percent }}{% if not forloop.last %}, {% endif %}{% endfor %}">
        {% for part in nei_context.parts %}{% if part.share %}<span class="segment is-nei-{{ part.key }}" style="width: {{ part.share|width_pct }}" title="{{ part.label }}: {{ part.share|percent }}"></span>{% endif %}{% endfor %}
    </div>
    <p class="emissions-legend">
        {% for part in nei_context.parts %}<span><span class="swatch is-nei-{{ part.key }}"></span>{{ part.label }} {{ part.share|percent }}</span>{% endfor %}
    </p>
    <p class="is-size-7"><a href="{% url 'emissions:about' %}#ammonia">Why ammonia matters, and why most of it isn't from permitted facilities</a></p>
</div>
```

`home.html` and `area.html`: right after the `{% if context_bar %}{% include 'emissions/includes/context-bar.html' %}{% endif %}` line, add `{% if nei_context %}{% include 'emissions/includes/nei-context-bar.html' %}{% endif %}`.

`includes/dairy-stats.html`: after the `carb_estimate` tile's `{% endif %}` (and after Phase 6's Water Board tile, wherever it sits), add:

```django
    {% if nei_dairy %}
    <div class="level-item has-text-centered"><div>
        <p class="heading">Ammonia, EPA estimate</p><p class="title">{{ nei_dairy.tons|whole }} <span class="is-size-5">tons/yr</span></p>
        <p class="is-size-7 has-text-grey">dairy cattle, {{ nei_dairy.share|percent }} of the county's ammonia ({{ nei_dairy.year }})</p>
    </div></div>
    {% endif %}
```

and one line in its comment block ("`nei_dairy` (county dairy pages): EPA's dairy-cattle ammonia and its share of the county's").

`about.html`, before `<h2 id="sources">` (after the Dairies list and any section the earlier phases put there):

```django
<h2 id="ammonia">Ammonia</h2>
<p>Ammonia isn't toxic at these levels, but it reacts with other pollution to form fine particles (PM2.5), the Valley's main winter air problem. Most Valley ammonia, about 90%, comes from livestock and fertilizer that aren't permitted facilities; only 7 dairies report ammonia to CARB. County figures are EPA and CARB model estimates for 2023, not measurements.</p>
<p>Facility ammonia is what each permitted facility reports to CARB, shown in tons per year beside the criteria pollutants (CARB delivers it in its toxics feed, but the explorer never weights or lists it as a toxic). County and Valley totals by source come from EPA's National Emissions Inventory (NEI), whose California point sources are CARB's own inventory resubmitted: the county pages' ammonia bar and the county dairy pages' dairy-cattle tile are EPA's 2023 estimates by source. {% if nei_stamp %}NEI {{ nei_stamp.version }} loaded.{% else %}No NEI data has been loaded yet.{% endif %}</p>
```

Sources list: `<li><a href="https://www.epa.gov/air-emissions-inventories/2023-nei-supporting-data-and-summaries">EPA 2023 National Emissions Inventory data summaries</a></li>`. Also edit the Dairies list item that says "CEPAM has no ammonia" to add ", so the county dairy pages take dairy-cattle ammonia from EPA's NEI" (keep the rest).

`datafiles/data-integrations.yaml`, under `category: Emissions Data` (after whichever entries the earlier phases added):

```yaml
    - name: EPA National Emissions Inventory
      logo: img/logo/epa-vertical.svg
      url: https://www.epa.gov/air-emissions-inventories/2023-nei-supporting-data-and-summaries
      description: EPA's National Emissions Inventory estimates every county's emissions by source every three years, from permitted facilities to livestock, fertilizer, vehicles and dust. SJVAir uses its 2023 ammonia estimates for the eight Valley counties, split by source, to show how small a share of the Valley's ammonia the permitted facilities on the map are, and how much comes from dairy cattle.
```

(Phase 4 added `img/logo/epa-vertical.svg`; confirm with `ls camp/static/img/logo/ | grep -i epa` and reuse whatever EPA logo is there.)

`assets/sass/sjvair/pages/emissions.sass`: beside the `.segment, .swatch` colour block (the `is-stationary` etc. rules), add:

```sass
    &.is-nei-dairy
      background: #7b4a12
    &.is-nei-livestock
      background: #b8772a
    &.is-nei-fertilizer
      background: #4a7c59
    &.is-nei-other
      background: #9aa5b1
```

Then `$ASSETS`.

- [ ] **Step 5: Run the tests and look**

`$TEST camp/apps/emissions/tests/test_nei.py camp/apps/emissions/tests/test_dairy_area_pages.py camp/apps/emissions/tests/test_views.py camp/apps/emissions/tests/test_areas_pages.py camp/apps/emissions/tests/test_dairies_pages.py` — all pass. On `:8003` (after Task 1's dev import) open `/tools/emissions/?pollutant=nh3`, Tulare County's page with `?pollutant=nh3` (the bar: livestock about 88%) and Tulare's dairies page (the tile, about 14,000 tons/yr, about 64%).

- [ ] **Step 6: Full run, smoke, commit, PR notes**

`$TEST camp/apps/emissions camp/api/v2/emissions` — all pass; `$MANAGE makemigrations --check --dry-run` → no changes. Run the smoke script; it must still pass (Part A adds no map code).

```
git -C <worktree> add camp/templates/emissions/includes/nei-context-bar.html
git -C <worktree> commit -m "feat(emissions): EPA's county ammonia by source on county pages, the home page and county dairy pages" -- camp/apps/emissions/nei.py camp/apps/emissions/views.py camp/apps/emissions/dairy_views.py camp/templates/emissions/includes/nei-context-bar.html camp/templates/emissions/home.html camp/templates/emissions/area.html camp/templates/emissions/includes/dairy-stats.html camp/templates/emissions/about.html assets/sass/sjvair/pages/emissions.sass datafiles/data-integrations.yaml camp/apps/emissions/tests/test_nei.py camp/apps/emissions/tests/test_dairy_area_pages.py
```

Part A's PR description (write it into `.superpowers/sdd/…/pr-body-ammonia.md`; no push until Derek says):

```
Ammonia (NH3) joins the explorer's picker under a "Precursor" heading, in tons/yr (Phase 1's ToxicEmission rows ÷ 2,000); map, list, sectors, Areas, region pages and near-me follow with no page code. CEPAM has no ammonia, so the NH3 scope's context bar is EPA's 2023 NEI county estimate by source (dairy cattle / other livestock / fertilizer / everything else) with the permitted-facility share above it; county dairy pages get an "Ammonia, EPA estimate" tile. Facility pages get an Ammonia row in the emissions table. Only 7 of 1,558 dairies report ammonia to CARB: facility ammonia is about 3% of the Valley's (the About page says so).
Deploy: 1. `migrate` (CountyNEI). 2. One-off dyno: `python manage.py import_nei --year 2023` (downloads 97 MB + 309 MB and streams a 2.8 GB CSV out of the second zip without unpacking; about 10 minutes; or download by hand and pass --sector-path/--nonpoint-path). The command bumps the explorer cache generation. Re-run per NEI release (every three years; add the new year's URLs to nei.URLS).
```

**Part A ends here.**

---

# Part B: Phase 7, Oil and gas wells

### Task 4: `Well`, `wellstar.py`, `import_wells` and the weekly task

**Files:**
- Modify: `camp/apps/emissions/models.py` (append after `CountyNEI`)
- Create: `camp/apps/emissions/migrations/0014_well.py` (generated; use the number `makemigrations` gives)
- Modify: `camp/apps/emissions/admin.py`
- Create: `camp/apps/emissions/wellstar.py`
- Create: `camp/apps/emissions/wells.py` (only the cache generation for now; Task 5 fills it)
- Create: `camp/apps/emissions/management/commands/import_wells.py`
- Modify: `camp/apps/emissions/tasks.py` (append)
- Create: `camp/apps/emissions/tests/data/wellstar-page.json` (a real one-page response, Step 2)
- Create: `camp/apps/emissions/tests/test_wellstar.py`; modify `camp/apps/emissions/tests/test_tasks.py` (append)

**Interfaces:**
- `Well(sqid, api unique, lease_name, well_number, designation, status, well_type, well_type_label, operator_code, operator_name, field_name, county FK, point, spud_date, in_hpz, directional, imported_at)`; `Well.Status` (`ACTIVE`, `IDLE`, `NEW`), `Well.HPZ` (`VERIFIED='Verified HPZ'`, `UNCERTAIN='Uncertainty Area'`, `NOT='Not Within HPZ'`); `Well.calgem_url`; `Well.label` ("LEASE 12-3").
- `wellstar.URL`, `wellstar.STATUSES`, `wellstar.OUT_FIELDS`, `wellstar.PAGE_SIZE = 5000`, `wellstar.SOURCE = 'wellstar'`.
- `wellstar.fetch_page(offset, counties) -> dict` (network; tests patch it), `wellstar.pages(counties) -> iterator of feature lists`, `wellstar.parse_feature(feature) -> dict | None`, `wellstar.parse_date(value) -> date | None`, `wellstar.apply(features) -> Report` (upsert on `api`, delete the rest, `SourceImport('wellstar')`, `wells.clear_caches()`).
- `wells.generation()`, `wells.clear_caches()`, `wells.key(*parts)` (the dairies pattern).
- Command `import_wells [--path JSON]`; task `tasks.import_wells`: `db_periodic_task(crontab(day_of_week='0', hour='12', minute='0'), priority=20)` under `lock_task('import-wells')`.

- [ ] **Step 1: The model, migration and admin**

Append to `camp/apps/emissions/models.py`:

```python
class Well(models.Model):
    """
    An oil or gas well in CalGEM's WellSTAR that is active, idle or newly
    permitted (plugged and cancelled wells aren't kept), where it is and who
    operates it. A regulatory record, not an emission: nothing here says what
    a well emits. `in_hpz` is CalGEM's own flag for SB 1137's 3,200-ft health
    protection zone around homes, schools and other sensitive receptors,
    still being revised. Refreshed weekly by import_wells.
    """

    class Status(models.TextChoices):
        ACTIVE = 'Active', _('Active')
        IDLE = 'Idle', _('Idle')
        NEW = 'New', _('New')

    class HPZ(models.TextChoices):
        VERIFIED = 'Verified HPZ', _('Verified health protection zone')
        UNCERTAIN = 'Uncertainty Area', _('Uncertainty area')
        NOT = 'Not Within HPZ', _('Not within a health protection zone')

    sqid = SqidsField(alphabet=shuffle_alphabet('emissions.Well'))
    api = models.CharField(_('API number'), max_length=14, unique=True)
    lease_name = models.CharField(_('Lease'), max_length=128, blank=True)
    well_number = models.CharField(_('Well number'), max_length=32, blank=True)
    designation = models.CharField(_('Designation'), max_length=64, blank=True)
    status = models.CharField(_('Status'), max_length=8, choices=Status.choices, db_index=True)
    well_type = models.CharField(_('Well type code'), max_length=8, blank=True)
    well_type_label = models.CharField(_('Well type'), max_length=64, blank=True)
    operator_code = models.CharField(_('Operator code'), max_length=16, blank=True)
    operator_name = models.CharField(_('Operator'), max_length=128, blank=True)
    field_name = models.CharField(_('Field'), max_length=128, blank=True)
    county = models.ForeignKey('regions.Region', verbose_name=_('County'), on_delete=models.PROTECT, related_name='wells')
    point = models.PointField(_('Point'))
    spud_date = models.DateField(_('Spud date'), null=True, blank=True)
    in_hpz = models.CharField(_('Health protection zone'), max_length=24, choices=HPZ.choices, blank=True)
    directional = models.BooleanField(_('Directionally drilled'), default=False)
    imported_at = models.DateTimeField(_('Imported at'), auto_now=True)

    class Meta:
        ordering = ['api']
        indexes = [models.Index(fields=['county', 'status'])]

    def __str__(self):
        return f'{self.label} ({self.api})'

    @property
    def label(self):
        return f'{self.lease_name} {self.well_number}'.strip() or self.api

    @property
    def calgem_url(self):
        return f'https://wellstar-public.conservation.ca.gov/WellSearch/Details?api={self.api}'
```

`$MANAGE makemigrations emissions --name well` (expected `0014_well.py`; keep whatever number it got; it must depend on Task 1's migration). In `admin.py`, add `Well` to the import and append:

```python
@admin.register(Well)
class WellAdmin(ReadOnlyAdminMixin, base_admin.ModelAdmin):
    list_display = ['api', 'lease_name', 'well_number', 'status', 'well_type_label', 'operator_name', 'field_name', 'county', 'in_hpz', 'spud_date']
    list_filter = ['status', 'in_hpz', 'county', 'directional']
    search_fields = ['api', 'lease_name', 'operator_name', 'field_name']
```

- [ ] **Step 2: The real sample page**

One real page of twelve features, so the parser is tested against CalGEM's field names and value shapes (the date encoding especially):

```bash
curl -sS 'https://gis.conservation.ca.gov/server/rest/services/WellSTAR/Wells/MapServer/0/query' \
  --data-urlencode "where=CountyName IN ('Kern','Fresno') AND WellStatus IN ('Active','Idle','New')" \
  --data-urlencode 'outFields=API,LeaseName,WellNumber,WellDesignation,WellStatus,WellType,WellTypeLabel,OperatorCode,OperatorName,FieldName,CountyName,Latitude,Longitude,SpudDate,inHPZ,isDirectionallyDrilled,GISSource' \
  --data-urlencode 'returnGeometry=false' --data-urlencode 'orderByFields=API' --data-urlencode 'resultOffset=0' \
  --data-urlencode 'resultRecordCount=12' --data-urlencode 'f=json' \
  -o /home/derek/dev/ccac/sjvair.com/.claude/worktrees/feature+ceidars-explorer/camp/apps/emissions/tests/data/wellstar-page.json
python3 -c "import json; d=json.load(open('/home/derek/dev/ccac/sjvair.com/.claude/worktrees/feature+ceidars-explorer/camp/apps/emissions/tests/data/wellstar-page.json')); print(len(d['features']), d.get('exceededTransferLimit')); print(d['features'][0]['attributes'])"
```

Read the printed attributes: note how `SpudDate` is encoded (an epoch-milliseconds integer is what ArcGIS returns for a date field; a `MM/DD/YYYY` string is what the hub CSV had) and how `isDirectionallyDrilled` is spelled (`Y`/`N`, `Yes`/`No`, `True`/`False` or a number). `parse_date` and `parse_bool` below accept all of these; if the real values are something else, extend them (not the sample). `exceededTransferLimit` should be `true` for a 12-row page.

- [ ] **Step 3: `wells.py` (the generation only) and `wellstar.py`**

Create `camp/apps/emissions/wells.py` with only:

```python
"""
The read side of CalGEM's wells (wellstar.py writes them): counts by area,
the schools and child-care centers with a well within 3,200 ft, and the Kern
oil & gas callout. Everything cached a day under a generation number that
import_wells bumps (clear_caches), the dairies pattern.
"""
import time

from django.core.cache import cache

CACHE_VERSION = 1
GENERATION_KEY = 'emissions:wells:generation'


def generation():
    """The current cache generation; a missing one starts from the clock so it never comes back to an old one."""
    value = cache.get(GENERATION_KEY)
    if value is None:
        value = int(time.time())
        cache.set(GENERATION_KEY, value, None)
    return value


def clear_caches():
    """Orphan every cached wells aggregate and API response: they're keyed under the generation."""
    cache.set(GENERATION_KEY, generation() + 1, None)


def key(*parts):
    return ':'.join(str(part) for part in (f'emissions:wells:v{CACHE_VERSION}', generation(), *parts))
```

Create `camp/apps/emissions/wellstar.py`:

```python
"""
CalGEM's WellSTAR wells, from the state's ArcGIS REST layer (CC-BY, no key):
every Active, Idle or New well in the covered counties, 5,000 a page. The
data.ca.gov package (wellstar-oil-and-gas-wells) documents it; its hub CSV
lags the service by months, so the service is the source.

Wells join nothing in CEIDARS (no shared key; don't try). They join regions
by point and schools by distance (wells.py).
"""
import math
import time
from dataclasses import dataclass
from datetime import date, datetime, timezone

import requests
from django.conf import settings
from django.contrib.gis.geos import Point
from django.db import transaction

from camp.apps.emissions.models import SourceImport, Well
from camp.apps.regions.models import Region

URL = 'https://gis.conservation.ca.gov/server/rest/services/WellSTAR/Wells/MapServer/0/query'
SOURCE = 'wellstar'
STATUSES = tuple(Well.Status.values)
OUT_FIELDS = (
    'API', 'LeaseName', 'WellNumber', 'WellDesignation', 'WellStatus', 'WellType', 'WellTypeLabel', 'OperatorCode',
    'OperatorName', 'FieldName', 'CountyName', 'Latitude', 'Longitude', 'SpudDate', 'inHPZ', 'isDirectionallyDrilled', 'GISSource',
)
PAGE_SIZE = 5000
RETRIES = 4
# The Well fields apply() compares and updates on a re-run.
FIELDS = (
    'lease_name', 'well_number', 'designation', 'status', 'well_type', 'well_type_label', 'operator_code',
    'operator_name', 'field_name', 'county', 'point', 'spud_date', 'in_hpz', 'directional',
)
TRUE_WORDS = {'y', 'yes', 'true', 't', '1'}
DATE_FORMATS = ('%m/%d/%Y', '%Y-%m-%d', '%m/%d/%Y %H:%M:%S', '%Y-%m-%dT%H:%M:%S')


class WellSTARError(RuntimeError):
    """The service answered with an error object instead of features."""


def where(counties=None):
    names = ', '.join(f"'{name}'" for name in (counties or settings.SJVAIR_COUNTIES))
    statuses = ', '.join(f"'{status}'" for status in STATUSES)
    return f'CountyName IN ({names}) AND WellStatus IN ({statuses})'


def params(offset, counties=None):
    return {
        'where': where(counties), 'outFields': ','.join(OUT_FIELDS), 'returnGeometry': 'false',
        # A stable order is what makes offset paging complete and duplicate-free.
        'orderByFields': 'API', 'resultOffset': offset, 'resultRecordCount': PAGE_SIZE, 'f': 'json',
    }


def fetch_page(offset, counties=None):
    """One page of the layer (a dict with `features` and `exceededTransferLimit`). The one network call here; tests patch it."""
    for attempt in range(RETRIES):
        try:
            response = requests.get(URL, params=params(offset, counties), timeout=120)
            response.raise_for_status()
            data = response.json()
            if 'error' in data:
                raise WellSTARError(str(data['error']))
            return data
        except (requests.RequestException, ValueError) as exc:
            if attempt == RETRIES - 1:
                raise
            time.sleep(2 ** attempt)


def pages(counties=None):
    """Yields each page's feature list until the service says it has no more."""
    offset = 0
    while True:
        data = fetch_page(offset, counties)
        features = data.get('features') or []
        yield features
        if not data.get('exceededTransferLimit') or len(features) < 1:
            return
        offset += len(features)


def parse_date(value):
    """A date from ArcGIS epoch milliseconds, or a 'MM/DD/YYYY' / ISO string; None for blank or nonsense."""
    if value in (None, '', 0):
        return None
    if isinstance(value, (int, float)):
        try:
            return datetime.fromtimestamp(value / 1000, tz=timezone.utc).date()
        except (OverflowError, OSError, ValueError):
            return None
    text = str(value).strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text[:19], fmt).date()
        except ValueError:
            continue
    return None


def parse_bool(value):
    if isinstance(value, bool):
        return value
    return str(value or '').strip().lower() in TRUE_WORDS


def _text(attrs, name, limit):
    return str(attrs.get(name) or '').strip()[:limit]


def parse_feature(feature):
    """
    A Well's field values from one REST feature, or None when it has no API
    number or no usable coordinates. `county_name` is CalGEM's ("Kern");
    apply() resolves it.
    """
    attrs = feature.get('attributes', feature)
    api = _text(attrs, 'API', 14)
    try:
        lat, lng = float(attrs.get('Latitude')), float(attrs.get('Longitude'))
    except (TypeError, ValueError):
        return None
    if not api or not (math.isfinite(lat) and math.isfinite(lng)) or not (-90 <= lat <= 90 and -180 <= lng <= 180) or (lat == 0 and lng == 0):
        return None
    status = _text(attrs, 'WellStatus', 8)
    if status not in STATUSES:
        return None
    hpz = _text(attrs, 'inHPZ', 24)
    return {
        'api': api,
        'lease_name': _text(attrs, 'LeaseName', 128),
        'well_number': _text(attrs, 'WellNumber', 32),
        'designation': _text(attrs, 'WellDesignation', 64),
        'status': status,
        'well_type': _text(attrs, 'WellType', 8),
        'well_type_label': _text(attrs, 'WellTypeLabel', 64),
        'operator_code': _text(attrs, 'OperatorCode', 16),
        'operator_name': _text(attrs, 'OperatorName', 128),
        'field_name': _text(attrs, 'FieldName', 128),
        'county_name': _text(attrs, 'CountyName', 64),
        'point': Point(lng, lat, srid=4326),
        'spud_date': parse_date(attrs.get('SpudDate')),
        'in_hpz': hpz if hpz in Well.HPZ.values else '',
        'directional': parse_bool(attrs.get('isDirectionallyDrilled')),
    }


@dataclass
class Report:
    fetched: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    deleted: int = 0
    skipped: int = 0

    def lines(self):
        return [
            f'WellSTAR: {self.fetched:,} features; {self.created:,} wells created, {self.updated:,} updated, '
            f'{self.unchanged:,} unchanged, {self.deleted:,} removed (no longer active, idle or new), {self.skipped:,} skipped.',
        ]


def _counties():
    """{'Kern': Region, 'Kern County': Region, ...} for the covered counties."""
    result = {}
    for region in Region.objects.counties():
        result[region.name] = region
        result[region.short_name] = region
    return result


def _same(well, values):
    for field in FIELDS:
        current = getattr(well, field)
        new = values[field]
        if field == 'point':
            if abs(current.x - new.x) > 1e-7 or abs(current.y - new.y) > 1e-7:
                return False
        elif field == 'county':
            if well.county_id != new.pk:
                return False
        elif current != new:
            return False
    return True


def apply(features):
    """
    Upsert every parsed feature on `api`, delete the wells not in `features`
    (plugged or cancelled since, or gone from the service), stamp
    SourceImport('wellstar') and bump the wells cache generation, in one
    transaction. `features` is the whole Valley (every page): a partial list
    would delete the rest.
    """
    from camp.apps.emissions import wells

    report = Report(fetched=len(features))
    counties = _counties()
    with transaction.atomic():
        existing = {well.api: well for well in Well.objects.all()}
        seen, new, changed = set(), [], []
        for feature in features:
            values = parse_feature(feature)
            if values is None:
                report.skipped += 1
                continue
            county = counties.get(values.pop('county_name'))
            if county is None or values['api'] in seen:
                report.skipped += 1
                continue
            values['county'] = county
            seen.add(values['api'])
            well = existing.get(values['api'])
            if well is None:
                new.append(Well(**values))
            elif _same(well, values):
                report.unchanged += 1
            else:
                for field, value in values.items():
                    setattr(well, field, value)
                changed.append(well)
        Well.objects.bulk_create(new, batch_size=1000)
        Well.objects.bulk_update(changed, list(FIELDS) + ['imported_at'], batch_size=1000)
        report.created, report.updated = len(new), len(changed)
        report.deleted, _ = Well.objects.exclude(api__in=seen).delete()
        SourceImport.objects.create(
            source=SOURCE, data_through=date.today(),
            notes={'wells': len(seen), 'created': report.created, 'updated': report.updated, 'deleted': report.deleted},
        )
    wells.clear_caches()
    return report
```

(`bulk_update` doesn't touch `auto_now`, hence `imported_at` in its field list after setting nothing on it: set `well.imported_at = timezone.now()` in the `changed` branch too, importing `from django.utils import timezone`.)

- [ ] **Step 4: The command and the task**

`camp/apps/emissions/management/commands/import_wells.py`:

```python
import json

from django.core.management.base import BaseCommand, CommandError

from camp.apps.emissions import wellstar


class Command(BaseCommand):
    help = (
        "Import CalGEM's active, idle and new oil and gas wells in the covered counties from the WellSTAR REST layer "
        '(about 66,000 wells, 14 pages, a minute). Upserts on the API number and removes wells no longer returned. '
        'Idempotent. --path reads a saved query response (a JSON file with "features") instead of the service.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--path', help='A saved WellSTAR query response (JSON) to import instead of fetching')

    def handle(self, *args, **options):
        features = []
        if options['path']:
            with open(options['path']) as handle:
                features = json.load(handle).get('features') or []
        else:
            try:
                for number, page in enumerate(wellstar.pages(), 1):
                    features.extend(page)
                    self.stdout.write(f'page {number}: {len(page):,} wells ({len(features):,} so far)')
            except (wellstar.WellSTARError, OSError) as exc:
                raise CommandError(f'WellSTAR: {exc}')
            except Exception as exc:  # requests errors, after the retries
                raise CommandError(f'WellSTAR: {exc}')
        if not features:
            raise CommandError('WellSTAR returned no wells; nothing changed.')
        report = wellstar.apply(features)
        for line in report.lines():
            self.stdout.write(line)
```

Append to `camp/apps/emissions/tasks.py` (Phase 4 created it with the `call_command`, `db_periodic_task`, `get_queue`, `crontab` imports):

```python
# CalGEM's WellSTAR layer is live; weekly keeps the map within a week of it.
# Sundays at 12:00 UTC.
@db_periodic_task(crontab(day_of_week='0', hour='12', minute='0'), priority=20)
def import_wells():
    with get_queue('primary').lock_task('import-wells'):
        call_command('import_wells')
```

- [ ] **Step 5: Tests**

Create `camp/apps/emissions/tests/test_wellstar.py`:

```python
"""
data/wellstar-page.json is one real 12-feature page of CalGEM's WellSTAR
Wells layer (Kern and Fresno, Active/Idle/New), fetched 2026-09-28 with the
curl in the Phase 7 plan, Task 4 Step 2.
"""
import json
import os
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from django.core.cache import cache
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from camp.apps.emissions import wells, wellstar
from camp.apps.emissions.models import SourceImport, Well
from camp.apps.emissions.tests.test_dairies import IN_KERN, NEAR_PLANT
from camp.apps.regions.models import Region

DATA = Path(__file__).parent / 'data'
SPUD_MS = int(datetime(2015, 3, 4, tzinfo=timezone.utc).timestamp() * 1000)


def feature(api, lnglat, county='Kern', status='Active', hpz='Not Within HPZ', **extra):
    attrs = {
        'API': api, 'LeaseName': 'KERN RIVER', 'WellNumber': api[-3:], 'WellDesignation': 'OG', 'WellStatus': status,
        'WellType': 'OG', 'WellTypeLabel': 'Oil & Gas', 'OperatorCode': 'A0123', 'OperatorName': 'TEST OIL LLC',
        'FieldName': 'Kern River', 'CountyName': county, 'Latitude': lnglat[1], 'Longitude': lnglat[0],
        'SpudDate': SPUD_MS, 'inHPZ': hpz, 'isDirectionallyDrilled': 'N', 'GISSource': 'CalGEM',
    }
    attrs.update(extra)
    return {'attributes': attrs}


FEATURES = [
    feature('0402900001', IN_KERN),
    feature('0402900002', (IN_KERN[0] + 0.001, IN_KERN[1]), status='Idle', hpz='Verified HPZ', isDirectionallyDrilled='Y'),
    feature('0402900003', (IN_KERN[0] + 0.002, IN_KERN[1]), status='New', SpudDate=None),
    feature('0401900004', NEAR_PLANT, county='Fresno'),
    feature('0403700005', (-118.2, 34.0), county='Los Angeles'),        # not covered: skipped
    feature('0402900006', (0, 0)),                                        # no coordinates: skipped
    feature('0402900007', IN_KERN, status='Plugged'),                     # never requested; skipped if it appears
    feature('', IN_KERN),                                                 # no API: skipped
]


def paged(features, size):
    """A fetch_page stand-in serving `features` `size` at a time, the way the service pages."""
    def fetch_page(offset, counties=None):
        page = features[offset:offset + size]
        return {'features': page, 'exceededTransferLimit': offset + size < len(features)}
    return fetch_page


class ParseTests(TestCase):
    def test_dates_and_bools(self):
        assert wellstar.parse_date(SPUD_MS) == date(2015, 3, 4)
        assert wellstar.parse_date('03/04/2015') == date(2015, 3, 4)
        assert wellstar.parse_date('2015-03-04T00:00:00') == date(2015, 3, 4)
        assert wellstar.parse_date(None) is None and wellstar.parse_date('') is None and wellstar.parse_date('soon') is None
        assert wellstar.parse_bool('Y') and wellstar.parse_bool('Yes') and wellstar.parse_bool(True) and wellstar.parse_bool(1)
        assert not wellstar.parse_bool('N') and not wellstar.parse_bool(None) and not wellstar.parse_bool('')

    def test_parse_feature(self):
        row = wellstar.parse_feature(FEATURES[1])
        assert row['api'] == '0402900002' and row['status'] == 'Idle' and row['in_hpz'] == 'Verified HPZ'
        assert row['directional'] is True and row['spud_date'] == date(2015, 3, 4) and row['county_name'] == 'Kern'
        assert (row['point'].x, row['point'].y) == (IN_KERN[0] + 0.001, IN_KERN[1]) and row['point'].srid == 4326
        assert wellstar.parse_feature(FEATURES[2])['spud_date'] is None
        for bad in FEATURES[5:]:
            assert wellstar.parse_feature(bad) is None, bad
        assert wellstar.parse_feature(feature('1', IN_KERN, inHPZ='Something new'))['in_hpz'] == ''

    def test_where_and_params(self):
        text = wellstar.where()
        assert "CountyName IN ('Fresno', 'Kern'" in text and "WellStatus IN ('Active', 'Idle', 'New')" in text
        params = wellstar.params(5000)
        assert params['resultOffset'] == 5000 and params['orderByFields'] == 'API' and params['returnGeometry'] == 'false'
        assert params['outFields'].split(',') == list(wellstar.OUT_FIELDS)

    def test_the_real_page(self):
        page = json.loads((DATA / 'wellstar-page.json').read_text())
        rows = [wellstar.parse_feature(f) for f in page['features']]
        assert len(rows) >= 10 and all(rows)
        assert page.get('exceededTransferLimit') is True
        for row in rows:
            assert 8 <= len(row['api']) <= 14 and row['status'] in wellstar.STATUSES
            assert row['county_name'] in ('Kern', 'Fresno') and 34 < row['point'].y < 38
        assert any(row['spud_date'] for row in rows), 'no SpudDate parsed: check its encoding in the sample'
        assert any(row['in_hpz'] for row in rows), 'no inHPZ value recognised: check Well.HPZ against the sample'


class PagesTests(TestCase):
    def test_pages_follow_the_transfer_limit(self):
        with patch('camp.apps.emissions.wellstar.fetch_page', side_effect=paged(FEATURES, 3)) as fetch:
            pages = list(wellstar.pages())
        assert [len(page) for page in pages] == [3, 3, 2]
        assert [c.args[0] for c in fetch.call_args_list] == [0, 3, 6]


class ApplyTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        cache.clear()
        self.kern = Region.objects.get(type=Region.Type.COUNTY, slug='kern')
        self.fresno = Region.objects.get(type=Region.Type.COUNTY, slug='fresno')

    def test_creates_matches_counties_and_skips(self):
        report = wellstar.apply(FEATURES)
        assert Well.objects.count() == 4
        idle = Well.objects.get(api='0402900002')
        assert idle.county == self.kern and idle.status == 'Idle' and idle.in_hpz == Well.HPZ.VERIFIED and idle.directional
        assert idle.label == 'KERN RIVER 002' and idle.calgem_url.endswith('api=0402900002') and idle.sqid
        assert Well.objects.get(api='0401900004').county == self.fresno
        assert (report.fetched, report.created, report.skipped) == (8, 4, 4)
        stamp = SourceImport.latest('wellstar')
        assert stamp.notes['wells'] == 4

    def test_rerun_upserts_and_removes(self):
        wellstar.apply(FEATURES)
        before = wells.generation()
        pk = Well.objects.get(api='0402900001').pk
        # 0001 becomes idle, 0002 unchanged, 0003 and the Fresno well are gone (plugged since), 0008 is new.
        again = [feature('0402900001', IN_KERN, status='Idle'), FEATURES[1], feature('0402900008', IN_KERN)]
        report = wellstar.apply(again)
        assert set(Well.objects.values_list('api', flat=True)) == {'0402900001', '0402900002', '0402900008'}
        assert Well.objects.get(api='0402900001').pk == pk and Well.objects.get(api='0402900001').status == 'Idle'
        assert (report.created, report.updated, report.unchanged, report.deleted) == (1, 1, 1, 2)
        assert wells.generation() == before + 1

    def test_a_duplicate_api_in_the_feed_is_written_once(self):
        wellstar.apply([FEATURES[0], FEATURES[0]])
        assert Well.objects.count() == 1


class CommandAndTaskTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def test_fetches_every_page(self):
        with patch('camp.apps.emissions.wellstar.fetch_page', side_effect=paged(FEATURES, 5)):
            call_command('import_wells')
        assert Well.objects.count() == 4

    def test_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'page.json')
            with open(path, 'w') as handle:
                json.dump({'features': FEATURES[:4]}, handle)
            call_command('import_wells', path=path)
        assert Well.objects.count() == 4

    def test_empty_feed_changes_nothing(self):
        wellstar.apply(FEATURES[:1])
        with patch('camp.apps.emissions.wellstar.fetch_page', side_effect=paged([], 5)):
            with pytest.raises(CommandError, match='no wells'):
                call_command('import_wells')
        assert Well.objects.count() == 1
```

Append to `camp/apps/emissions/tests/test_tasks.py`:

```python
class ImportWellsTaskTests(TestCase):
    @patch('camp.apps.emissions.tasks.call_command')
    def test_runs_the_command_under_the_lock(self, call_command):
        tasks.import_wells.call_local()
        call_command.assert_called_once_with('import_wells')
```

Run: `$TEST camp/apps/emissions/tests/test_wellstar.py camp/apps/emissions/tests/test_tasks.py camp/apps/emissions/tests/test_models.py` — all pass. If `test_the_real_page` fails on the spud date or the HPZ value, the real encoding differs from the accepted forms: extend `parse_date` / `Well.HPZ` to the real one and say so in the commit message. Also `$MANAGE makemigrations --check --dry-run` → no changes.

- [ ] **Step 6: Load the dev server and commit**

`docker exec $(docker ps --filter publish=8003 --format '{{.Names}}') python manage.py migrate`, then `… python manage.py import_wells` (about a minute; expect roughly 66,000 wells, most in Kern).

```
git -C <worktree> add camp/apps/emissions/migrations/0014_well.py camp/apps/emissions/wellstar.py camp/apps/emissions/wells.py camp/apps/emissions/management/commands/import_wells.py camp/apps/emissions/tests/data/wellstar-page.json camp/apps/emissions/tests/test_wellstar.py
git -C <worktree> commit -m "feat(emissions): import CalGEM's active, idle and new wells from WellSTAR, weekly" -- camp/apps/emissions/models.py camp/apps/emissions/migrations/0014_well.py camp/apps/emissions/admin.py camp/apps/emissions/wellstar.py camp/apps/emissions/wells.py camp/apps/emissions/management/commands/import_wells.py camp/apps/emissions/tasks.py camp/apps/emissions/tests/data/wellstar-page.json camp/apps/emissions/tests/test_wellstar.py camp/apps/emissions/tests/test_tasks.py
```

---

### Task 5: `wells.py`: area counts, schools near wells, the Kern callout

**Files:**
- Modify: `camp/apps/emissions/wells.py` (append)
- Create: `camp/apps/emissions/tests/test_wells.py`

**Interfaces:**
- Constants: `wells.HPZ_FEET = 3200`, `wells.SCHOOL_TOP = 10`, `wells.COARSE_DEGREES = 0.012`, `wells.KERN_SLUG = 'kern'`, `wells.BENZENE_ID = '71432'`.
- `wells.stamp() -> SourceImport | None`.
- `wells.well_q(area) -> Q` (on `Well`) and `wells.location_q(area) -> Q` (on `regions.Location`) for an `areas.RegionArea` or `areas.RadiusArea`.
- `wells.area_summary(area) -> dict | None`: `{'total', 'active', 'idle', 'new', 'hpz'}`; None when `total == 0`. Cached under `key('area', area.key)`.
- `wells.locations_near_wells() -> {location pk: well count}` Valley-wide, every location with at least one well within 3,200 ft. Cached under `key('near-schools')`.
- `wells.schools_near_wells(area) -> {'count': int, 'top': [{'sqid', 'name', 'type_label', 'wells'}]}` (the top `SCHOOL_TOP` by well count, then name). Cached under `key('schools', area.key)`.
- `wells.kern_callout(year) -> dict | None`: `{'year', 'rog_share', 'benzene_share', 'facilities'}` from CEIDARS (every Kern facility with a record that year, minor sources included); None without any Kern ROG that year. Cached under `stats.prefix()`.

- [ ] **Step 1: Write the failing tests**

Create `camp/apps/emissions/tests/test_wells.py`:

```python
from django.contrib.gis.geos import Point
from django.core.cache import cache
from django.test import TestCase

from camp.apps.emissions import areas, wells
from camp.apps.emissions.models import EmissionsRecord, Facility, ToxicEmission, ToxicPollutant, Well
from camp.apps.emissions.tests.test_areas import AROUND_PLANT, make
from camp.apps.emissions.tests.test_dairies import IN_KERN, NEAR_PLANT
from camp.apps.regions.models import Location, Region

# One degree of latitude is about 364,000 ft: a point `feet` north of another, to within ~0.3%.
FEET_PER_DEGREE_LAT = 364_000


def north_of(point, feet):
    return Point(point.x, point.y + feet / FEET_PER_DEGREE_LAT, srid=4326)


def make_well(api, lnglat, county, status='Active', hpz='Not Within HPZ', **fields):
    point = lnglat if isinstance(lnglat, Point) else Point(*lnglat, srid=4326)
    return Well.objects.create(
        api=api, lease_name='TEST LEASE', well_number=api[-2:], status=status, in_hpz=hpz, county=county, point=point,
        operator_name='TEST OIL LLC', field_name='Test Field', well_type_label='Oil & Gas', **fields,
    )


def location(name, point, type=Location.Type.PUBLIC_SCHOOL):
    return Location.objects.create(name=name, type=type, external_id=name, source='test', point=point)


class WellsTestCase(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        cache.clear()
        self.fresno = Region.objects.get(type=Region.Type.COUNTY, slug='fresno')
        self.kern = Region.objects.get(type=Region.Type.COUNTY, slug='kern')
        self.plant = Facility.objects.get(name='TEST PLANT')  # (-119.787, 36.737)
        self.a = make_well('0402900001', IN_KERN, self.kern)
        self.b = make_well('0402900002', (IN_KERN[0] + 0.001, IN_KERN[1]), self.kern, status='Idle', hpz='Verified HPZ')
        self.c = make_well('0402900003', (IN_KERN[0] + 0.002, IN_KERN[1]), self.kern, status='New', hpz='Verified HPZ')
        self.d = make_well('0401900004', NEAR_PLANT, self.fresno)


class AreaSummaryTests(WellsTestCase):
    def test_counts_by_county_point_and_radius(self):
        assert wells.area_summary(areas.RegionArea(self.kern)) == {'total': 3, 'active': 1, 'idle': 1, 'new': 1, 'hpz': 2}
        assert wells.area_summary(areas.RegionArea(self.fresno)) == {'total': 1, 'active': 1, 'idle': 0, 'new': 0, 'hpz': 0}
        tract = make(Region.Type.TRACT, 'T1', AROUND_PLANT)
        assert wells.area_summary(areas.RegionArea(tract))['total'] == 1
        assert wells.area_summary(areas.RadiusArea(36.737, -119.787, 1))['total'] == 1
        assert wells.area_summary(areas.RadiusArea(36.0, -120.5, 1)) is None
        assert wells.area_summary(areas.RegionArea(Region.objects.get(type=Region.Type.COUNTY, slug='tulare'))) is None

    def test_cached_under_the_generation(self):
        area = areas.RegionArea(self.kern)
        assert wells.area_summary(area)['total'] == 3
        make_well('0402900009', IN_KERN, self.kern)
        assert wells.area_summary(area)['total'] == 3
        wells.clear_caches()
        assert wells.area_summary(area)['total'] == 4


class SchoolsNearWellsTests(WellsTestCase):
    def setUp(self):
        super().setUp()
        # Around TEST PLANT: a school with wells at 3,000 and 3,400 ft north, a preschool 200 ft from the Fresno well.
        self.school = location('PLANT ELEMENTARY', self.plant.point)
        make_well('0401900010', north_of(self.plant.point, 3000), self.fresno)
        make_well('0401900011', north_of(self.plant.point, 3400), self.fresno)
        self.preschool = location('OILFIELD PRESCHOOL', north_of(Point(*NEAR_PLANT, srid=4326), 200), Location.Type.CHILD_CARE)
        self.far = location('FAR HIGH', Point(-120.5, 36.0, srid=4326))

    def test_schools_near_wells_boundary(self):
        counts = wells.locations_near_wells()
        assert counts[self.school.pk] == 1          # 3,000 ft in, 3,400 ft out; the well by NEAR_PLANT is ~1,900 ft away: in
        assert self.far.pk not in counts

    def test_area_rows(self):
        result = wells.schools_near_wells(areas.RegionArea(self.fresno))
        assert result['count'] == 2
        assert [(row['name'], row['wells'], row['type_label']) for row in result['top']] == [
            ('PLANT ELEMENTARY', 2, 'Public school'), ('OILFIELD PRESCHOOL', 1, 'Child care'),
        ]
        assert result['top'][0]['sqid'] == self.school.sqid
        assert wells.schools_near_wells(areas.RegionArea(self.kern)) == {'count': 0, 'top': []}
        near = wells.schools_near_wells(areas.RadiusArea(36.737, -119.787, 1))
        assert near['count'] == 2

    def test_top_ten(self):
        for i in range(12):
            location(f'CROWD {i}', north_of(self.plant.point, 100 + i))
        result = wells.schools_near_wells(areas.RegionArea(self.fresno))
        assert result['count'] == 14 and len(result['top']) == wells.SCHOOL_TOP


class KernCalloutTests(WellsTestCase):
    def test_shares(self):
        # Kern 2024: TEST GAS STATION reported 0.2 tons ROG and 0.5 lbs benzene (the fixture); add an oil-gas grouping.
        rig = Facility.objects.create(county_code=15, air_district=Region.objects.get(pk=9001), facid=77, name='HEAVY OIL WESTERN',
                                      county=self.kern, sic_code=1311, sector='oil-gas', address={})
        EmissionsRecord.objects.create(facility=rig, year=2024, rog='0.8')
        ToxicEmission.objects.create(facility=rig, year=2024, pollutant=ToxicPollutant.objects.get(carb_id='71432'), lbs='3')
        callout = wells.kern_callout(2024)
        assert callout['year'] == 2024 and callout['facilities'] == 1
        assert abs(callout['rog_share'] - 0.8) < 1e-9 and abs(callout['benzene_share'] - 3 / 3.5) < 1e-9

    def test_none_without_data(self):
        assert wells.kern_callout(1999) is None
        EmissionsRecord.objects.filter(facility__county=self.kern).update(rog=None)
        cache.clear()
        assert wells.kern_callout(2024) is None

    def test_benzene_share_is_none_without_benzene(self):
        ToxicEmission.objects.filter(facility__county=self.kern).delete()
        rig = Facility.objects.create(county_code=15, air_district=Region.objects.get(pk=9001), facid=78, name='LIGHT OIL',
                                      county=self.kern, sic_code=1311, sector='oil-gas', address={})
        EmissionsRecord.objects.create(facility=rig, year=2024, rog='0.2')
        callout = wells.kern_callout(2024)
        assert abs(callout['rog_share'] - 0.5) < 1e-9 and callout['benzene_share'] is None
```

- [ ] **Step 2: Run them and watch them fail**

`$TEST camp/apps/emissions/tests/test_wells.py` — `AttributeError: … 'area_summary'`.

- [ ] **Step 3: Fill in `wells.py`**

Add to the imports: `import math`, `from django.contrib.gis.geos import Polygon`, `from django.contrib.gis.measure import D`, `from django.db.models import Count, Exists, OuterRef, Q, Sum`, `from camp.apps.emissions import areas, stats`, `from camp.apps.emissions.models import EmissionsRecord, Facility, SourceImport, ToxicEmission, Well`, `from camp.apps.regions.models import Location, Region`. Then append:

```python
# SB 1137's health protection zone: 3,200 ft of a home, school, child-care
# center or other sensitive receptor (PRC 3280). The coarse box (in degrees,
# generous: 3,200 ft is 0.0088 deg of latitude) is the index prefilter; the
# exact check is a great-circle distance.
HPZ_FEET = 3200
COARSE_DEGREES = 0.012
FEET_PER_MILE = 5280
MILES_PER_DEGREE = 69.0
SCHOOL_TOP = 10
KERN_SLUG = 'kern'
BENZENE_ID = '71432'


def stamp():
    return SourceImport.latest('wellstar')


def well_q(area):
    """The wells in an area: a county by Well.county, any other region by point-in-boundary, a radius by distance."""
    if isinstance(area, areas.RadiusArea):
        return area._within('point')
    region = area.region
    if region.type == Region.Type.COUNTY:
        return Q(county=region)
    return Q(point__intersects=region.boundary.geometry)


def location_q(area):
    """The schools and child-care centers (regions.Location) in an area, by point."""
    if isinstance(area, areas.RadiusArea):
        return area._within('point')
    return Q(point__intersects=area.region.boundary.geometry)


def area_summary(area):
    """
    Wells in the area by status, and how many CalGEM has verified as inside
    a health protection zone; None when there are none (the line is hidden).
    """
    def compute():
        row = Well.objects.filter(well_q(area)).aggregate(
            total=Count('pk'),
            active=Count('pk', filter=Q(status=Well.Status.ACTIVE)),
            idle=Count('pk', filter=Q(status=Well.Status.IDLE)),
            new=Count('pk', filter=Q(status=Well.Status.NEW)),
            hpz=Count('pk', filter=Q(in_hpz=Well.HPZ.VERIFIED)),
        )
        return row if row['total'] else None
    return cache.get_or_set(key('area', area.key), compute, stats.CACHE_TIMEOUT)


def _bbox(point, miles):
    """A degree bbox around `point`, slightly generous: the GiST prefilter before the exact distance (schools.py's pattern)."""
    dlat = miles / MILES_PER_DEGREE
    dlng = miles / (MILES_PER_DEGREE * max(math.cos(math.radians(point.y)), 0.01))
    box = Polygon.from_bbox((point.x - dlng, point.y - dlat, point.x + dlng, point.y + dlat))
    box.srid = 4326
    return box


def locations_near_wells():
    """
    {Location pk: wells within HPZ_FEET} for every school and child-care
    center in the Valley with at least one (about 90 of 2,800). Two steps:
    one query finds the candidates with a well inside a coarse degree box
    around them (the index does the work), then each candidate gets an exact
    great-circle count. Cached a day under the wells generation.
    """
    def compute():
        coarse = Well.objects.filter(point__dwithin=(OuterRef('point'), COARSE_DEGREES))
        candidates = Location.objects.annotate(near=Exists(coarse)).filter(near=True).only('pk', 'point')
        result = {}
        for place in candidates:
            point = place.point
            if point.srid is None:
                point.srid = 4326
            count = Well.objects.filter(
                point__bboverlaps=_bbox(point, HPZ_FEET / FEET_PER_MILE), point__distance_lte=(point, D(ft=HPZ_FEET)),
            ).count()
            if count:
                result[place.pk] = count
        return result
    return cache.get_or_set(key('near-schools'), compute, stats.CACHE_TIMEOUT)


def schools_near_wells(area):
    """
    The area's schools and child-care centers with a well within 3,200 ft:
    how many, and the SCHOOL_TOP with the most wells (then by name), each
    {sqid, name, type_label, wells}.
    """
    def compute():
        counts = locations_near_wells()
        if not counts:
            return {'count': 0, 'top': []}
        rows = [
            {'sqid': place.sqid, 'name': place.name, 'type_label': str(Location.SHORT_TYPES[place.type]), 'wells': counts[place.pk]}
            for place in Location.objects.filter(location_q(area), pk__in=list(counts)).order_by('name')
        ]
        rows.sort(key=lambda row: (-row['wells'], row['name']))
        return {'count': len(rows), 'top': rows[:SCHOOL_TOP]}
    return cache.get_or_set(key('schools', area.key), compute, stats.CACHE_TIMEOUT)


def kern_callout(year):
    """
    What Kern's oil & gas permit groupings report to CARB in `year`, as a
    share of every Kern facility's total (minor sources included): ROG, and
    benzene from ToxicEmission. None when Kern reported no ROG that year;
    benzene_share is None when nobody reported benzene. Cached under the
    explorer generation (a CEIDARS or toxics import clears it).
    """
    def compute():
        kern = Region.objects.counties().filter(slug=KERN_SLUG).first()
        if kern is None:
            return None
        records = EmissionsRecord.objects.filter(year=year, facility__county=kern)
        rog_total = records.aggregate(t=Sum('rog'))['t']
        if not rog_total:
            return None
        oil_gas = records.filter(facility__sector=Facility.Sector.OIL_GAS)
        rog_oil = oil_gas.aggregate(t=Sum('rog'))['t'] or 0
        benzene = ToxicEmission.objects.filter(year=year, facility__county=kern, pollutant__carb_id=BENZENE_ID)
        benzene_total = benzene.aggregate(t=Sum('lbs'))['t']
        benzene_oil = benzene.filter(facility__sector=Facility.Sector.OIL_GAS).aggregate(t=Sum('lbs'))['t'] or 0
        return {
            'year': year,
            'facilities': oil_gas.values('facility_id').distinct().count(),
            'rog_share': float(rog_oil) / float(rog_total),
            'benzene_share': float(benzene_oil) / float(benzene_total) if benzene_total else None,
        }
    return cache.get_or_set(f'{stats.prefix()}:kern-oil-gas:{year}', compute, stats.CACHE_TIMEOUT)
```

Notes for the implementer: `point__dwithin` with a plain float on a geodetic geometry field is a degree distance (what we want for the coarse box; `D(ft=…)` there would raise); `point__distance_lte=(point, D(ft=…))` runs `ST_DistanceSphere`, metres, as `schools.py` does. `Location.SHORT_TYPES` maps `Location.Type` values to the labels the schools card uses. If `Exists(coarse)` with `OuterRef('point')` inside `dwithin` errors on the installed Django, replace the candidate query with `Location.objects.filter(point__bboverlaps=<the union bbox of every well>)` — but don't: it works on Django 5 (spatial lookups accept expressions), and the test says so.

- [ ] **Step 4: Run and commit**

`$TEST camp/apps/emissions/tests/test_wells.py camp/apps/emissions/tests/test_wellstar.py` — all pass.

```
git -C <worktree> add camp/apps/emissions/tests/test_wells.py
git -C <worktree> commit -m "feat(emissions): well counts by area, schools within 3,200 ft of a well, and the Kern oil & gas callout" -- camp/apps/emissions/wells.py camp/apps/emissions/tests/test_wells.py
```

---

### Task 6: The wells GeoJSON and detail endpoints

**Files:**
- Create: `camp/api/v2/emissions/wells.py`
- Modify: `camp/api/v2/emissions/urls.py`
- Test: `camp/api/v2/emissions/tests.py` (append)

**Interfaces:**
- `GET /api/2.0/emissions/wells/geojson/` (`api:v2:emissions:wells-geojson`): a FeatureCollection of every stored well, `id` = sqid, geometry a Point rounded to 5 places, `properties` exactly `{'id', 's', 'h'}` (`s` the status, `h` 1 for a verified HPZ else 0); collection `properties` `{'wells': n, 'imported': ISO date | None}`. Cached a day under the wells generation (`WellsCachedEndpointMixin`).
- `GET /api/2.0/emissions/wells/<sqid>/` (`api:v2:emissions:well-detail`): `{'id', 'api', 'label', 'lease_name', 'well_number', 'status', 'well_type', 'operator', 'field', 'county', 'spud_year', 'in_hpz', 'directional', 'url'}`; 404 for an unknown sqid.

- [ ] **Step 1: Write the failing tests**

Append to `camp/api/v2/emissions/tests.py` (imports: `from camp.apps.emissions import wells`, `from camp.apps.emissions.tests.test_wells import make_well`, `from camp.apps.emissions.tests.test_dairies import IN_KERN` if not already imported):

```python
class WellEndpointTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        cache.clear()
        kern = Region.objects.get(type=Region.Type.COUNTY, slug='kern')
        self.active = make_well('0402900001', IN_KERN, kern, spud_date='2015-03-04')
        self.idle = make_well('0402900002', (IN_KERN[0] + 0.001, IN_KERN[1]), kern, status='Idle', hpz='Verified HPZ', directional=True)

    def test_geojson_is_lean(self):
        response = self.client.get(reverse('api:v2:emissions:wells-geojson'))
        assert response.status_code == 200
        body = response.json()
        assert body['properties']['wells'] == 2 and body['properties']['imported'] is None
        by_id = {f['id']: f for f in body['features']}
        idle = by_id[self.idle.sqid]
        assert idle['properties'] == {'id': self.idle.sqid, 's': 'Idle', 'h': 1}
        assert by_id[self.active.sqid]['properties']['h'] == 0
        assert idle['geometry'] == {'type': 'Point', 'coordinates': [round(IN_KERN[0] + 0.001, 5), IN_KERN[1]]}

    def test_geojson_cache_follows_the_wells_generation(self):
        assert len(self.client.get(reverse('api:v2:emissions:wells-geojson')).json()['features']) == 2
        Well.objects.filter(pk=self.idle.pk).delete()
        assert len(self.client.get(reverse('api:v2:emissions:wells-geojson')).json()['features']) == 2
        wells.clear_caches()
        assert len(self.client.get(reverse('api:v2:emissions:wells-geojson')).json()['features']) == 1

    def test_detail(self):
        body = self.client.get(reverse('api:v2:emissions:well-detail', args=[self.idle.sqid])).json()
        assert body == {
            'id': self.idle.sqid, 'api': '0402900002', 'label': 'TEST LEASE 02', 'lease_name': 'TEST LEASE', 'well_number': '02',
            'status': 'Idle', 'well_type': 'Oil & Gas', 'operator': 'TEST OIL LLC', 'field': 'Test Field', 'county': 'Kern County',
            'spud_year': None, 'in_hpz': 'Verified HPZ', 'directional': True, 'url': self.idle.calgem_url,
        }
        assert self.client.get(reverse('api:v2:emissions:well-detail', args=[self.active.sqid])).json()['spud_year'] == 2015
        assert self.client.get(reverse('api:v2:emissions:well-detail', args=['nope'])).status_code == 404
```

(Import `Well` from the models there too.)

- [ ] **Step 2: Run them and watch them fail**

`$TEST camp/api/v2/emissions/tests.py::WellEndpointTests` — `NoReverseMatch`.

- [ ] **Step 3: The endpoints**

Create `camp/api/v2/emissions/wells.py`:

```python
from django.http import Http404
from resticus import generics

from camp.apps.emissions import wells
from camp.apps.emissions.models import Well
from camp.utils.views import CachedEndpointMixin


class WellsCachedEndpointMixin(CachedEndpointMixin):
    """Response caching that a re-import (wells.clear_caches) invalidates."""

    def get_view_cache_key(self):
        return f'{super().get_view_cache_key()}|g:{wells.generation()}'


class WellGeoJSONBase(generics.Endpoint):
    # get() lives on this un-cached base so the mixin's get() on the subclass
    # is the one dispatched to (the explorer endpoints' pattern).
    def get(self, request):
        features = []
        for well in Well.objects.only('id', 'status', 'in_hpz', 'point').order_by('pk').iterator(chunk_size=5000):
            features.append({
                'type': 'Feature',
                'id': well.sqid,
                'geometry': {'type': 'Point', 'coordinates': [round(well.point.x, 5), round(well.point.y, 5)]},
                'properties': {'id': well.sqid, 's': well.status, 'h': 1 if well.in_hpz == Well.HPZ.VERIFIED else 0},
            })
        stamp = wells.stamp()
        return {
            'type': 'FeatureCollection',
            'properties': {'wells': len(features), 'imported': stamp.imported_at.date().isoformat() if stamp else None},
            'features': features,
        }


class WellGeoJSON(WellsCachedEndpointMixin, WellGeoJSONBase):
    """
    Every active, idle or new oil and gas well CalGEM lists in the covered
    counties, as GeoJSON points for the facility map's wells overlay. Lean
    by design (about 66,000 points): properties are `id` (for the detail
    endpoint), `s` (Active / Idle / New) and `h` (1 inside a verified health
    protection zone). Source: CalGEM WellSTAR (CC-BY); a regulatory record,
    not emissions. Cached a day; a re-import invalidates it.
    """
    cache_timeout = 60 * 60 * 24
    cache_key_version = 1


class WellDetail(generics.Endpoint):
    """One well, for the map popup: lease and number, status, type, operator, field, spud year, HPZ status and its CalGEM record."""

    def get(self, request, sqid):
        well = Well.objects.filter(sqid=sqid).select_related('county').first()
        if well is None:
            raise Http404('No such well.')
        return {
            'id': well.sqid,
            'api': well.api,
            'label': well.label,
            'lease_name': well.lease_name,
            'well_number': well.well_number,
            'status': well.status,
            'well_type': well.well_type_label,
            'operator': well.operator_name,
            'field': well.field_name,
            'county': well.county.name,
            'spud_year': well.spud_date.year if well.spud_date else None,
            'in_hpz': well.in_hpz,
            'directional': well.directional,
            'url': well.calgem_url,
        }
```

`camp/api/v2/emissions/urls.py`: import `wells` beside the others and add, **before** the `'<str:facility_id>/'` catch-all:

```python
    path('wells/geojson/', wells.WellGeoJSON.as_view(), name='wells-geojson'),
    path('wells/<str:sqid>/', wells.WellDetail.as_view(), name='well-detail'),
```

- [ ] **Step 4: Run and commit**

`$TEST camp/api/v2/emissions/tests.py` — all pass. Check the payload size on the dev server: `curl -s http://localhost:8003/api/2.0/emissions/wells/geojson/ | wc -c` (expect roughly 6–8 MB uncompressed; the response is gzipped by the front end).

```
git -C <worktree> add camp/api/v2/emissions/wells.py
git -C <worktree> commit -m "feat(api): wells GeoJSON and detail endpoints for the facility map overlay" -- camp/api/v2/emissions/wells.py camp/api/v2/emissions/urls.py camp/api/v2/emissions/tests.py
```

---

### Task 7: The map overlay, the region/near-me/sector page blocks, the facility note, About

**Files:**
- Modify: `camp/apps/emissions/views.py` (`facility_map_config`, new `wells_overlay`, `is_kern`, `wells_block`; `MapPage`, `RegionPage`, `NearMe`, `SectorDetail`, `AreaPage`, `About`)
- Create: `camp/templates/emissions/includes/wells-block.html`, `camp/templates/emissions/includes/oil-gas-callout.html`
- Modify: `camp/templates/emissions/area.html`, `sector-detail.html`, `facility-detail.html`, `about.html`
- Modify: `assets/js/emissions/facility-map.js`, `assets/sass/sjvair/pages/emissions.sass`, `datafiles/data-integrations.yaml`
- Create: `camp/apps/emissions/tests/test_wells_pages.py`

**Interfaces:**
- `views.wells_overlay(get, *, default=False) -> {'on': bool, 'default': bool}`; `views.is_kern(region) -> bool`; `views.wells_block(area, scope, *, kern=False) -> dict | None` (`{'summary', 'schools', 'kern', 'stamp'}`).
- `facility_map_config(..., wells=None)`: container attributes `data-wells-url`, `data-well-url`, `data-wells` (`'1'` or `''`), `data-wells-default` (`'1'` or `''`); all blank when `wells` is None.
- Context: `wells_block` on region and near-me pages; `kern_callout` and `wells_stamp` on the oil-gas sector page; `wells_stamp` on About.
- JS: `FacilityMap.prototype.setWells(on)`, `loadWells()`, `applyWells()`, `zoomToCluster(feature)`, `openWellPopup(feature, lngLat)`; `?wells=1|0` written by `writeState` when the state differs from the page default; `data-wells-loaded="1"` on the container once the wells source has data.

- [ ] **Step 1: Write the failing tests**

Create `camp/apps/emissions/tests/test_wells_pages.py`:

```python
import re

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from camp.apps.emissions import views
from camp.apps.emissions.models import EmissionsRecord, Facility, ToxicEmission, ToxicPollutant
from camp.apps.emissions.tests.test_areas_pages import map_data
from camp.apps.emissions.tests.test_dairies import IN_KERN, NEAR_PLANT
from camp.apps.emissions.tests.test_wells import location, make_well, north_of
from camp.apps.regions.models import Region


class WellsPagesTestCase(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        cache.clear()
        self.fresno = Region.objects.get(type=Region.Type.COUNTY, slug='fresno')
        self.kern = Region.objects.get(type=Region.Type.COUNTY, slug='kern')
        self.plant = Facility.objects.get(name='TEST PLANT')

    def get(self, url, params=None, status=200):
        response = self.client.get(url, params or {})
        assert response.status_code == status, response.status_code
        return response.content.decode()

    def add_wells(self):
        make_well('0402900001', IN_KERN, self.kern)
        make_well('0402900002', (IN_KERN[0] + 0.001, IN_KERN[1]), self.kern, status='Idle', hpz='Verified HPZ')
        make_well('0401900004', NEAR_PLANT, self.fresno)
        make_well('0401900010', north_of(self.plant.point, 3000), self.fresno)
        location('PLANT ELEMENTARY', self.plant.point)

    def add_kern_oil_gas(self):
        rig = Facility.objects.create(county_code=15, air_district=Region.objects.get(pk=9001), facid=77, name='HEAVY OIL WESTERN',
                                      county=self.kern, sic_code=1311, sector='oil-gas', address={})
        EmissionsRecord.objects.create(facility=rig, year=2024, rog='0.8')
        ToxicEmission.objects.create(facility=rig, year=2024, pollutant=ToxicPollutant.objects.get(carb_id='71432'), lbs='3')
        return rig


class OverlayConfigTests(WellsPagesTestCase):
    def test_wells_overlay_helper(self):
        assert views.wells_overlay({}) == {'on': False, 'default': False}
        assert views.wells_overlay({}, default=True) == {'on': True, 'default': True}
        assert views.wells_overlay({'wells': '1'}) == {'on': True, 'default': False}
        assert views.wells_overlay({'wells': '0'}, default=True) == {'on': False, 'default': True}
        assert views.wells_overlay({'wells': 'x'}, default=True)['on'] is True

    def test_off_by_default_on_by_request(self):
        for url in (reverse('emissions:map'), self.fresno.get_emissions_url(), reverse('emissions:near-me') + '?lat=36.737&lng=-119.787'):
            content = self.get(url)
            assert map_data(content, 'wells') == '' and map_data(content, 'wells-default') == '', url
            assert map_data(content, 'wells-url') == reverse('api:v2:emissions:wells-geojson'), url
            assert '{id}' in map_data(content, 'well-url')
        content = self.get(reverse('emissions:map'), {'wells': '1'})
        assert map_data(content, 'wells') == '1' and map_data(content, 'wells-default') == ''

    def test_on_by_default_for_kern_and_the_oil_gas_sector(self):
        content = self.get(self.kern.get_emissions_url())
        assert map_data(content, 'wells') == '1' and map_data(content, 'wells-default') == '1'
        assert map_data(self.get(self.kern.get_emissions_url(), {'wells': '0'}), 'wells') == ''
        content = self.get(reverse('emissions:sector-detail', args=['oil-gas']))
        assert map_data(content, 'wells') == '1'
        assert map_data(self.get(reverse('emissions:sector-detail', args=['glass'])), 'wells') == ''

    def test_a_facilitys_own_map_has_no_overlay(self):
        content = self.get(self.plant.get_absolute_url())
        assert map_data(content, 'wells-url') == '' and map_data(content, 'wells') == ''


class WellsBlockTests(WellsPagesTestCase):
    def test_nothing_without_wells(self):
        content = self.get(self.fresno.get_emissions_url())
        assert 'id="wells"' not in content and 'href="#wells"' not in content

    def test_region_block(self):
        self.add_wells()
        content = self.get(self.fresno.get_emissions_url(), {'year': '2024'})
        block = content[content.index('id="wells"'):]
        assert '<a href="#wells">Oil &amp; gas wells</a>' in content
        assert '2 active · 0 idle · 0 in a verified health-protection zone (3,200 ft of homes or schools)' in block
        assert '<strong>1</strong> school or child-care center here has an active or idle well within 3,200 ft' in block
        assert re.search(r'PLANT ELEMENTARY.*?Public school · 2 wells', block, re.S)
        assert 'Oil &amp; gas facilities reported' not in block  # the Kern sentence is Kern's
        assert 'href="/tools/emissions/about/#oil-gas"' in block

    def test_kern_block_has_the_callout(self):
        self.add_wells()
        self.add_kern_oil_gas()
        content = self.get(self.kern.get_emissions_url(), {'year': '2024'})
        block = content[content.index('id="wells"'):]
        assert '1 active · 1 idle · 1 in a verified health-protection zone' in block
        assert "Oil &amp; gas facilities reported 80% of Kern&#x27;s permitted-facility ROG and 86% of its benzene in 2024" in block \
            or "Oil &amp; gas facilities reported 80% of Kern's permitted-facility ROG and 86% of its benzene in 2024" in block
        assert 'No school or child-care center here has a well within 3,200 ft.' in block

    def test_near_me_block(self):
        self.add_wells()
        content = self.get(reverse('emissions:near-me'), {'lat': '36.737', 'lng': '-119.787', 'radius': '1', 'year': '2024'})
        assert 'id="wells"' in content and '2 active' in content

    def test_sector_page_callout(self):
        self.add_kern_oil_gas()
        content = self.get(reverse('emissions:sector-detail', args=['oil-gas']), {'year': '2024'})
        assert "80% of Kern" in content and 'permit groupings that can span a whole oil field' in content
        assert 'id="wells"' not in content
        assert '80% of Kern' not in self.get(reverse('emissions:sector-detail', args=['glass']), {'year': '2024'})


class FacilityNoteTests(WellsPagesTestCase):
    def test_oil_gas_note_replaces_the_schools_card(self):
        location('PLANT ELEMENTARY', north_of(self.plant.point, 500))
        Facility.objects.filter(pk=self.plant.pk).update(sector='oil-gas', point_source='census')
        content = self.get(self.plant.get_absolute_url())
        assert 'This is a district permit grouping that can span a whole oil field. Its map point is the operator&#x27;s address, not a well.' in content \
            or "Its map point is the operator's address, not a well." in content
        assert 'Schools and child care nearby' not in content
        Facility.objects.filter(pk=self.plant.pk).update(sector='glass')
        content = self.get(self.plant.get_absolute_url())
        assert 'district permit grouping' not in content and 'Schools and child care nearby' in content


class AboutTests(WellsPagesTestCase):
    def test_about_and_integrations(self):
        content = self.get(reverse('emissions:about'))
        assert '<h2 id="oil-gas">Oil and gas</h2>' in content
        assert "Well counts are CalGEM's regulatory records, not emissions." in content or 'Well counts are CalGEM&#x27;s regulatory records' in content
        assert 'No well data has been imported yet.' in content
        assert 'WellSTAR' in self.get('/about/integrations/')
```

- [ ] **Step 2: Run them and watch them fail**

`$TEST camp/apps/emissions/tests/test_wells_pages.py` — `AttributeError: … 'wells_overlay'`.

- [ ] **Step 3: Views**

`views.py`: import `wells` beside `areas, dairies, nei, stats`. Add above `facility_map_config`:

```python
def wells_overlay(get, *, default=False):
    """
    The map's Oil & gas wells overlay: on by default where `default` says
    (Kern County's page, the oil-gas sector page), off elsewhere; ?wells=1|0
    overrides either way so the state can be shared.
    """
    raw = get.get('wells')
    on = raw == '1' if raw in ('0', '1') else default
    return {'on': on, 'default': default}


def is_kern(region):
    """Kern County's page: the overlay's default is on and the block carries the oil & gas callout."""
    return region.type == Region.Type.COUNTY and region.slug == wells.KERN_SLUG
```

`facility_map_config`: add `wells=None` to the signature; in `config`, after `'radius': radius,`:

```python
        # The Oil & gas wells overlay (CalGEM WellSTAR, wells.py): offered where
        # `wells` is set (the map page, region, near-me and sector pages) and
        # never on a facility's own map. `wells` is its initial state, `wells_default`
        # the page's default (the JS writes ?wells= only when they differ).
        'wells_url': reverse('api:v2:emissions:wells-geojson') if wells else '',
        'well_url': reverse('api:v2:emissions:well-detail', args=['__id__']).replace('__id__', '{id}') if wells else '',
        'wells': '1' if wells and wells['on'] else '',
        'wells_default': '1' if wells and wells['default'] else '',
```

and mention `wells` in the docstring. Then:

- `MapPage.get_context_data`: pass `wells=wells_overlay(self.request.GET)` to `facility_map_config`.
- `RegionPage.get_map_config`: pass `wells=wells_overlay(self.request.GET, default=is_kern(self.region))`.
- `NearMe.get_map_config`: pass `wells=wells_overlay(self.request.GET)`.
- `SectorDetail.get_context_data`: `facility_map_config(scope, mode='compact', sector=self.sector, wells=wells_overlay(self.request.GET, default=self.sector == Facility.Sector.OIL_GAS))`, plus `kern_callout=wells.kern_callout(scope.year) if self.sector == Facility.Sector.OIL_GAS else None` and `wells_stamp=wells.stamp()`.

Add, near `dairy_block`:

```python
def wells_block(area, scope, *, kern=False):
    """
    The "Oil & gas wells" section on a region or near-me page, or None when
    the area has no wells: the counts, the schools and child-care centers
    with a well within 3,200 ft, and on Kern County's page what the oil & gas
    permit groupings report (wells.kern_callout).
    """
    summary = wells.area_summary(area)
    if summary is None:
        return None
    return {
        'summary': summary,
        'schools': wells.schools_near_wells(area),
        'kern': wells.kern_callout(scope.year) if kern else None,
        'stamp': wells.stamp(),
    }
```

In `AreaPage.get_context_data`, beside the other `kwargs.setdefault(...)` lines: `kwargs.setdefault('wells_block', None)`. In `RegionPage.get_context_data`, in `extra`: `extra['wells_block'] = wells_block(areas.RegionArea(region), self.get_scope(), kern=is_kern(region))`. In `NearMe.get_context_data`: `wells_block=wells_block(self.near, self.get_scope()),`. `About.get_context_data`: `wells_stamp=wells.stamp()`.

- [ ] **Step 4: Templates**

Create `camp/templates/emissions/includes/oil-gas-callout.html`:

```django
{% load emissions_explorer %}
{% comment %}
What Kern's oil & gas permit groupings report to CARB (wells.kern_callout), on
Kern County's page and the oil-gas sector page. Context: `callout`.
{% endcomment %}
<p class="oil-gas-callout"><strong>Oil &amp; gas facilities</strong> reported {{ callout.rog_share|percent }} of Kern's permitted-facility ROG{% if callout.benzene_share is not None %} and {{ callout.benzene_share|percent }} of its benzene{% endif %} in {{ callout.year }}.
   <span class="has-text-grey">CARB's oil &amp; gas "facilities" are district permit groupings that can span a whole oil field; their map points aren't well locations.</span></p>
```

Create `camp/templates/emissions/includes/wells-block.html`:

```django
{% load humanize %}
{% comment %}
A region or near-me page's "Oil & gas wells" section (views.wells_block):
CalGEM's active, idle and new wells here by status and how many sit in a
verified health protection zone; on Kern County's page the oil & gas callout;
the schools and child-care centers with a well within 3,200 ft (SB 1137's
distance), the ten with the most wells listed. Nothing when the area has no wells.
{% endcomment %}
<section class="wells-block mt-5" id="wells">
    <h2 class="title is-4"><span class="icon"><span class="fa-duotone fa-fw fa-oil-well explorer-icon is-wells" aria-hidden="true"></span></span> Oil &amp; gas wells</h2>
    {% with s=wells_block.summary %}
    <p class="wells-line">{{ s.active|intcomma }} active · {{ s.idle|intcomma }} idle{% if s.new %} · {{ s.new|intcomma }} new{% endif %} · {{ s.hpz|intcomma }} in a verified health-protection zone (3,200 ft of homes or schools)</p>
    {% endwith %}
    {% if wells_block.kern %}{% include 'emissions/includes/oil-gas-callout.html' with callout=wells_block.kern %}{% endif %}
    {% with schools=wells_block.schools %}
    {% if schools.count %}
    <p><strong>{{ schools.count|intcomma }}</strong> {% if schools.count == 1 %}school or child-care center here has{% else %}schools and child-care centers here have{% endif %} an active or idle well within 3,200 ft{% if schools.top|length < schools.count %} (the {{ schools.top|length }} with the most wells){% endif %}:</p>
    <ul class="wells-schools">
        {% for row in schools.top %}<li>{{ row.name }} <span class="has-text-grey is-size-7">{{ row.type_label }} · {{ row.wells|intcomma }} well{{ row.wells|pluralize }}</span></li>{% endfor %}
    </ul>
    {% else %}
    <p>No school or child-care center here has a well within 3,200 ft.</p>
    {% endif %}
    {% endwith %}
    <p class="is-size-7 has-text-grey">CalGEM's records{% if wells_block.stamp %}, fetched {{ wells_block.stamp.imported_at|date:"N j, Y" }}{% endif %}: counts of wells, not emissions; idle wells can still leak; plugged wells aren't shown; distances are straight lines from the school's map point. <a href="{% url 'emissions:about' %}#oil-gas">About</a></p>
</section>
```

`area.html`: after the `<div class="columns mt-5">…</div>` holding "By sector" and the trend chart, and before `{% if dairy_block %}`, add `{% if wells_block %}{% include 'emissions/includes/wells-block.html' %}{% endif %}`. In the section nav (whatever condition Phase 3 left: `{% if dairy_block.has_dairies or within.any or community or tract_ces %}`), add `or wells_block` to the condition and, right before the Dairies link, `{% if wells_block %} · <a href="#wells">Oil &amp; gas wells</a>{% endif %}`.

`sector-detail.html`: after the stat-row `</div>` / `{% endif %}` block and before `<div class="columns">`, add `{% if kern_callout %}{% include 'emissions/includes/oil-gas-callout.html' with callout=kern_callout %}{% endif %}`.

`facility-detail.html`: Phase 2's schools card sits in `<div class="columns facility-cards">` as `{% if nearby is not None %}<div class="column is-half">{% include 'emissions/includes/schools-card.html' %}</div>{% endif %}`. Make it:

```django
    {% if nearby is not None %}
    <div class="column is-half">
        {% include 'emissions/includes/schools-card.html' %}
    </div>
    {% elif facility.sector == 'oil-gas' %}
    <div class="column is-half">
        <div class="card">
            <header class="card-header"><p class="card-header-title">About this location</p></header>
            <div class="card-content">
                <p>This is a district permit grouping that can span a whole oil field. Its map point is the operator's address, not a well.</p>
                <p class="is-size-7 has-text-grey"><a href="{% url 'emissions:about' %}#oil-gas">Where the wells are</a></p>
            </div>
        </div>
    </div>
    {% endif %}
```

`about.html`, before `<h2 id="sources">` (after the Ammonia section):

```django
<h2 id="oil-gas">Oil and gas</h2>
<p>CARB's inventory lists oil and gas production as district permit groupings ("HEAVY OIL WESTERN", "LIGHT OIL") that can cover a whole field, and half of Kern's have no map point at all; where one exists it's the operator's address. So the explorer also shows <strong>where the wells are</strong>: every active, idle and newly permitted well in CalGEM's WellSTAR database (about 66,000 in the eight counties, nearly all in Kern), as an <em>Oil &amp; gas wells</em> overlay on the map, as counts on region pages, and as the schools and child-care centers with a well within 3,200 ft, the distance state law (SB 1137) sets for a health protection zone around homes, schools and other sensitive receptors.</p>
<p>Well counts are CalGEM's regulatory records, not emissions. Idle wells can still leak; plugged wells aren't shown. Health-protection-zone status is CalGEM's and is still being revised. Distances to schools are straight lines from the school's map point (the law measures from property lines). Oil &amp; gas "facilities" in CARB's inventory are permit groupings that can cover a whole field; their map points aren't well locations.</p>
<p>{% if wells_stamp %}Wells last fetched from CalGEM {{ wells_stamp.imported_at|date:"N j, Y" }}; refreshed weekly.{% else %}No well data has been imported yet.{% endif %}</p>
```

Sources list: `<li><a href="https://data.ca.gov/dataset/wellstar-oil-and-gas-wells">CalGEM WellSTAR oil and gas wells</a></li>`. `datafiles/data-integrations.yaml`, under Emissions Data:

```yaml
    - name: CalGEM WellSTAR
      logo: img/logo/ca-open-data.png
      url: https://data.ca.gov/dataset/wellstar-oil-and-gas-wells
      description: The California Geologic Energy Management Division's WellSTAR database is the state's record of every oil and gas well — its operator, field, status and whether it sits in a health protection zone under SB 1137. SJVAir shows the Valley's active, idle and new wells as a map overlay, counts them on region pages, and lists the schools and child-care centers with a well within 3,200 ft.
```

(Check `ls camp/static/img/logo/` for an existing CalGEM or Department of Conservation logo first and prefer it; the Open Data one is the fallback the CIWQS entry uses.)

- [ ] **Step 5: The overlay in `facility-map.js`**

Constants, after `METERS_PER_MILE`:

```js
  // The Oil & gas wells overlay (CalGEM WellSTAR, /api/2.0/emissions/wells/geojson/):
  // one point per well, clustered by the GeoJSON source until CLUSTER_MAX_ZOOM.
  // Status colours; a red ring marks a verified health protection zone.
  var WELL_COLORS = { Active: '#b45309', Idle: '#6b7280', New: '#2563eb' };
  var WELL_HPZ_COLOR = '#dc2626';
  var CLUSTER_COLOR = '#7c2d12';
  var CLUSTER_MAX_ZOOM = 11;
  var CLUSTER_RADIUS = 40;
  var WELL_STATUSES = ['Active', 'Idle', 'New'];
```

Constructor, after the `areas-fill` listeners:

```js
    this.wellsData = null;
    this.wellsRequest = 0;
    this.map.on('click', 'wells-clusters', function (evt) { self.zoomToCluster(evt.features[0]); });
    this.map.on('click', 'wells', function (evt) { self.openWellPopup(evt.features[0], evt.lngLat); });
```

and extend the cursor loop to `['facilities', 'areas-fill', 'wells-clusters', 'wells']`.

`readViewState`, at the end:

```js
    // The wells overlay: offered where the page gave a URL; its default is the
    // page's (Kern County, the oil-gas sector), the URL may override it.
    this.wellsEnabled = !!this.data.wellsUrl;
    this.wellsDefault = this.data.wellsDefault === '1';
    this.wells = this.wellsEnabled && this.data.wells === '1';
```

`addLayers`, after the `districts` layer and before `facilities` (wells draw under the facility circles):

```js
    // Wells: clustered until CLUSTER_MAX_ZOOM; cluster size by count, colour
    // by its active share; single wells by status, ringed when in a verified HPZ.
    this.shell.ensureSource('wells', {
      cluster: true, clusterMaxZoom: CLUSTER_MAX_ZOOM, clusterRadius: CLUSTER_RADIUS,
      clusterProperties: {
        active: ['+', ['case', ['==', ['get', 's'], 'Active'], 1, 0]],
        hpz: ['+', ['get', 'h']],
      },
    });
    this.shell.ensureLayer({
      id: 'wells-clusters', type: 'circle', source: 'wells', filter: ['has', 'point_count'],
      paint: {
        'circle-radius': ['step', ['get', 'point_count'], 10, 50, 14, 500, 19, 5000, 26],
        'circle-color': CLUSTER_COLOR,
        'circle-opacity': ['interpolate', ['linear'], ['/', ['get', 'active'], ['get', 'point_count']], 0, 0.35, 1, 0.8],
        'circle-stroke-color': '#ffffff', 'circle-stroke-width': 1.5,
      },
    });
    this.shell.ensureLayer({
      id: 'wells', type: 'circle', source: 'wells', filter: ['!', ['has', 'point_count']],
      paint: {
        'circle-radius': 4,
        'circle-color': ['match', ['get', 's'], 'Active', WELL_COLORS.Active, 'Idle', WELL_COLORS.Idle, 'New', WELL_COLORS.New, WELL_COLORS.Idle],
        'circle-opacity': 0.85,
        'circle-stroke-color': ['case', ['==', ['get', 'h'], 1], WELL_HPZ_COLOR, '#ffffff'],
        'circle-stroke-width': ['case', ['==', ['get', 'h'], 1], 2, 0.5],
      },
    });
```

and at the end of `addLayers`, after `this.applyView();`: `this.applyWells();`. In `load()`, after `this.loadOutline();`: `if (this.wells) this.loadWells();`. New methods, after `showOutline`:

```js
  // The overlay's layers follow `this.wells`; the legend's checkbox too.
  FacilityMap.prototype.applyWells = function () {
    var on = this.wellsEnabled && this.wells;
    if (this.map) {
      ['wells-clusters', 'wells'].forEach(function (id) {
        if (this.map.getLayer(id)) this.map.setLayoutProperty(id, 'visibility', on ? 'visible' : 'none');
      }, this);
    }
  };

  // Every Valley well, fetched once per page load (about 66,000 points, a
  // day's cache server-side) and only when the overlay is on.
  FacilityMap.prototype.loadWells = function () {
    var self = this;
    if (!this.wellsEnabled) return;
    if (this.wellsData) {
      this.shell.setSourceData('wells', this.wellsData);
      this.el.dataset.wellsLoaded = '1';
      return;
    }
    var request = ++this.wellsRequest;
    this.el.dataset.wellsLoaded = '';
    getJson(this.data.wellsUrl)
      .then(function (collection) {
        if (request !== self.wellsRequest || !self.map) return;
        self.wellsData = collection;
        self.shell.setSourceData('wells', collection);
        self.shell.updateLegend();
        self.el.dataset.wellsLoaded = '1';
      })
      .catch(function (err) {
        if (request !== self.wellsRequest || !self.map) return;
        logError('failed to load the wells', err);
      });
  };

  FacilityMap.prototype.setWells = function (on) {
    if (!this.wellsEnabled) return;
    this.wells = !!on;
    this.applyWells();
    this.syncUrl();
    this.shell.updateLegend();
    if (this.wells) this.loadWells();
  };

  // A cluster click zooms to where it breaks apart (MapLibre's expansion
  // zoom: a Promise on current SDKs, a callback on older ones).
  FacilityMap.prototype.zoomToCluster = function (feature) {
    var self = this;
    var source = this.map.getSource('wells');
    var center = feature.geometry.coordinates;
    var go = function (zoom) {
      if (typeof zoom !== 'number') return;
      self.map.easeTo({ center: center, zoom: zoom + 0.5, duration: self.shell.reducedMotion ? 0 : 400 });
    };
    var result = source.getClusterExpansionZoom(feature.properties.cluster_id, function (err, zoom) { if (!err) go(zoom); });
    if (result && typeof result.then === 'function') result.then(go).catch(function (err) { logError('cluster zoom', err); });
  };

  FacilityMap.prototype.openWellPopup = function (feature, lngLat) {
    var self = this;
    var id = feature.properties.id;
    var popup = this.shell.placePopup('<div class="facility-popup well-popup"><p>Loading…</p></div>', lngLat);
    getJson((this.data.wellUrl || '').replace('{id}', encodeURIComponent(id)))
      .then(function (well) {
        if (self.shell.popup !== popup) return;
        popup.setHTML('<div class="facility-popup well-popup">' +
          '<p class="facility-popup-name">' + escapeHtml(well.label) + '</p>' +
          '<p>' + escapeHtml(well.status) + (well.well_type ? ' · ' + escapeHtml(well.well_type) : '') + '</p>' +
          (well.operator ? '<p>' + escapeHtml(well.operator) + (well.field ? ', ' + escapeHtml(well.field) + ' field' : '') + '</p>' : '') +
          '<p>' + (well.spud_year ? 'Drilled ' + escapeHtml(String(well.spud_year)) + ' · ' : '') + escapeHtml(well.in_hpz || 'HPZ status unknown') + '</p>' +
          '<p><a href="' + escapeHtml(well.url) + '">CalGEM record →</a></p>' +
          '</div>');
        if (self.shell.panPopupIntoView) self.shell.panPopupIntoView(popup);
      })
      .catch(function (err) {
        if (self.shell.popup !== popup) return;
        popup.setHTML('<div class="facility-popup well-popup"><p>Couldn\'t load this well.</p></div>');
        logError('failed to load a well', err);
      });
  };

  // The legend's overlay row: the checkbox, and while it's on the key.
  FacilityMap.prototype.wellsLegendHtml = function () {
    if (!this.wellsEnabled) return '';
    var html = '<div class="legend-overlay"><label class="legend-toggle"><input type="checkbox" data-wells' +
      (this.wells ? ' checked' : '') + '> Oil &amp; gas wells</label>';
    if (this.wells) {
      html += '<p class="legend-wells">' + WELL_STATUSES.map(function (status) {
        return '<span class="legend-well"><span class="legend-swatch is-well" style="background: ' + WELL_COLORS[status] + '"></span>' + status + '</span>';
      }).join('') + '<span class="legend-well"><span class="legend-swatch is-well is-hpz"></span>Verified health-protection zone</span></p>' +
        '<p class="legend-note">CalGEM records, not emissions. Zoom in to split the clusters; click a well for its record.</p>';
    }
    return html + '</div>';
  };
```

In `legend()`: every branch that assigns `legend.innerHTML = …` (the Compare branch, the "No facilities here reported" branch and the plain one) appends `+ this.wellsLegendHtml()`; in `areaLegend` the same for both of its assignments. In `onChrome`, after the `bindControls` calls:

```js
    // The legend's wells checkbox is re-rendered with the legend, so the
    // handler is delegated to the legend body, bound once.
    var legendBody = this.shell.legendBodyEl;
    if (legendBody && !legendBody.getAttribute('data-wells-bound')) {
      legendBody.setAttribute('data-wells-bound', '1');
      legendBody.addEventListener('change', function (event) {
        if (event.target && event.target.hasAttribute('data-wells')) self.setWells(event.target.checked);
      });
    }
```

(`legendBodyEl` is what `updateLegend` passes to `legend()`; check the exact property name in `assets/js/maps/shell.js` — `Shell.prototype.updateLegend` reads it — and use that.) In `writeState`, at the end:

```js
    // The wells overlay: written only when it differs from the page's default.
    if (this.wellsEnabled && this.wells !== this.wellsDefault) params.set('wells', this.wells ? '1' : '0'); else params.delete('wells');
```

In `onAdopt`, after `this.readViewState(); this.applyView();`: `this.applyWells(); if (this.wells) this.loadWells();` (the data survives the adopt: it's the whole Valley). Update the file header comment: a paragraph "Overlays: Oil & gas wells (CalGEM), clustered, from data-wells-url; on where data-wells is 1; the legend's checkbox toggles it and ?wells= carries it."

- [ ] **Step 6: Styles**

`assets/sass/sjvair/pages/emissions.sass`: find the emissions legend rules (grep `legend-note` under `assets/sass`; add beside them, in the same file and nesting) :

```sass
  .legend-overlay
    margin-top: 0.5rem
    padding-top: 0.5rem
    border-top: 1px solid $grey-lighter
  .legend-toggle
    display: flex
    align-items: center
    gap: 0.4rem
    font-weight: 600
  .legend-wells
    display: flex
    flex-wrap: wrap
    gap: 0.25rem 0.75rem
    margin: 0.25rem 0
  .legend-swatch.is-well
    width: 0.7rem
    height: 0.7rem
    border-radius: 50%
    display: inline-block
    margin-right: 0.25rem
    &.is-hpz
      background: transparent
      border: 2px solid #dc2626
  .wells-block
    .wells-line
      font-weight: 600
    .wells-schools
      margin: 0.5rem 0 0.75rem 1.25rem
      list-style: disc
  .oil-gas-callout
    margin: 0.5rem 0 1rem
  .explorer-icon.is-wells
    color: #7c2d12
```

(Use the file's existing variable for the light grey border if `$grey-lighter` isn't in scope.) Then `node --check /home/derek/dev/ccac/sjvair.com/.claude/worktrees/feature+ceidars-explorer/assets/js/emissions/facility-map.js` and `$ASSETS`.

- [ ] **Step 7: Run the tests, then look**

`$TEST camp/apps/emissions/tests/test_wells_pages.py camp/apps/emissions/tests/test_wells.py camp/apps/emissions/tests/test_views.py camp/apps/emissions/tests/test_areas_pages.py camp/apps/emissions/tests/test_facility_page.py camp/apps/emissions/tests/test_schools.py` — all pass. On `:8003` (Task 4's dev import done): open `/tools/emissions/map/`, tick "Oil & gas wells" in the legend, zoom to Bakersfield: clusters, then wells with red rings around Bakersfield's fields; click a cluster (it zooms), click a well (the popup, the CalGEM link); the URL carries `wells=1`. Open Kern County's page: on by default, the block with the callout and the schools list (about 75 in Kern). Open an oil-gas facility's page: the note.

- [ ] **Step 8: Commit**

```
git -C <worktree> add camp/templates/emissions/includes/wells-block.html camp/templates/emissions/includes/oil-gas-callout.html camp/apps/emissions/tests/test_wells_pages.py
git -C <worktree> commit -m "feat(emissions): oil & gas wells overlay, region well counts and schools near wells, the Kern callout" -- camp/apps/emissions/views.py camp/templates/emissions/includes/wells-block.html camp/templates/emissions/includes/oil-gas-callout.html camp/templates/emissions/area.html camp/templates/emissions/sector-detail.html camp/templates/emissions/facility-detail.html camp/templates/emissions/about.html assets/js/emissions/facility-map.js assets/sass/sjvair/pages/emissions.sass datafiles/data-integrations.yaml camp/apps/emissions/tests/test_wells_pages.py
```

(Plus the built bundle files by explicit path if the repo tracks them, per the precedent in Global Constraints.)

---

### Task 8: Smoke checks, the full run, Part B's notes

**Files:**
- Modify: `scripts/emissions_map_smoke.py` (docstring; new checks before the Dairies block)

**Interfaces:**
- Consumes `window.EmissionsFacilityMap.instances()[0]` with `setWells`, `zoomToCluster`, `openWellPopup`, the container's `data-wells-loaded`, the legend's `[data-wells]` checkbox.

- [ ] **Step 1: Add the wells checks**

Before the Dairies block (`driver.get(args.base + '/tools/emissions/dairies/')`), after Phase 1's toxics checks, add:

```python
        # The Oil & gas wells overlay: off on the map page until ticked, then
        # clustered over Kern; a cluster click zooms, a well click fetches its
        # record; the state lands in the URL; Kern County's page has it on.
        driver.get(args.base + '/tools/emissions/map/')
        check(results, 'map loads with the wells overlay off', wait_loaded(driver)
              and driver.execute_script("return window.EmissionsFacilityMap.instances()[0].wells;") is False
              and driver.execute_script("return !!document.querySelector('.facility-map-legend [data-wells]');"))
        driver.execute_script("window.EmissionsFacilityMap.instances()[0].setWells(true);")
        deadline = time.time() + MAP_TIMEOUT
        while time.time() < deadline and driver.execute_script(
                "return document.querySelector('.facility-map').dataset.wellsLoaded;") != '1':
            time.sleep(0.25)
        check(results, 'ticking the overlay loads the wells and writes wells=1',
              driver.execute_script("return document.querySelector('.facility-map').dataset.wellsLoaded;") == '1'
              and query(driver).get('wells') == ['1'], driver.current_url)
        driver.execute_script("window.EmissionsFacilityMap.instances()[0].map.jumpTo({center: [-119.1, 35.4], zoom: 9});")
        time.sleep(1.5)
        clusters = driver.execute_script(
            "var m = window.EmissionsFacilityMap.instances()[0];"
            "return m.map.queryRenderedFeatures({layers: ['wells-clusters']}).length;")
        check(results, 'clusters render over Kern at zoom 9', clusters > 0, f'{clusters} clusters')
        zoom_before = driver.execute_script("return window.EmissionsFacilityMap.instances()[0].map.getZoom();")
        driver.execute_script(
            "var m = window.EmissionsFacilityMap.instances()[0];"
            "var f = m.map.queryRenderedFeatures({layers: ['wells-clusters']})[0]; if (f) m.zoomToCluster(f);")
        time.sleep(1.5)
        zoom_after = driver.execute_script("return window.EmissionsFacilityMap.instances()[0].map.getZoom();")
        check(results, 'a cluster click zooms in', zoom_after > zoom_before, f'{zoom_before:.1f} -> {zoom_after:.1f}')
        driver.execute_script("window.EmissionsFacilityMap.instances()[0].map.jumpTo({center: [-119.02, 35.42], zoom: 13.5});")
        time.sleep(1.5)
        popup = driver.execute_script("""
            var m = window.EmissionsFacilityMap.instances()[0];
            var f = m.map.queryRenderedFeatures({layers: ['wells']})[0];
            if (!f) return '';
            m.openWellPopup(f, f.geometry.coordinates);
            return 'opened';
        """)
        deadline = time.time() + 10
        text = ''
        while time.time() < deadline and 'CalGEM record' not in text:
            text = driver.execute_script("var el = document.querySelector('.well-popup'); return el ? el.textContent : '';")
            time.sleep(0.25)
        check(results, 'a well click shows its record with the CalGEM link', popup == 'opened' and 'CalGEM record' in text, text[:120])
        legend = driver.execute_script("return document.querySelector('.facility-map-legend').textContent;")
        check(results, 'the legend keys the statuses and the HPZ ring', 'Active' in legend and 'health-protection zone' in legend)
        driver.execute_script("window.EmissionsFacilityMap.instances()[0].setWells(false);")
        time.sleep(0.3)
        check(results, 'unticking clears wells= and hides the layer', 'wells' not in query(driver)
              and driver.execute_script("return window.EmissionsFacilityMap.instances()[0].map.getLayoutProperty('wells', 'visibility');") == 'none')
```

Then Kern County's page. The script already reaches Tulare County's page somewhere (read how: a fixed `args.base + '/tools/emissions/region/<sqid>/tulare/'`, or a lookup through the home page's find-area data); build `kern_url` for Kern the same way and add:

```python
        # Kern County's page: on by default, and the block on the page.
        driver.get(kern_url)
        check(results, "Kern County's page has the overlay on by default and the wells block",
              wait_loaded(driver) and driver.execute_script("return document.querySelector('.facility-map').dataset.wells;") == '1'
              and driver.execute_script("return !!document.getElementById('wells');"))
```

Update the module docstring with one sentence about the wells checks. Run the smoke script; every check must pass (a failing pre-existing check unrelated to wells is reported, not fixed here).

- [ ] **Step 2: Full run**

`$TEST camp -q` — everything passes (a transient failure that passes alone is the shared test DB; re-run once). `$MANAGE makemigrations --check --dry-run` → "No changes detected".

- [ ] **Step 3: Commit and write the notes**

```
git -C <worktree> commit -m "test(emissions): smoke the wells overlay, clusters, a well popup and Kern's default" -- scripts/emissions_map_smoke.py
```

Part B's PR description (`.superpowers/sdd/…/pr-body-wells.md`; no push until Derek says):

```
CalGEM's WellSTAR wells (Active, Idle, New; ~66,000 in the eight counties, nearly all Kern) as an "Oil & gas wells" overlay on the facility map, region, near-me and sector pages (legend checkbox; off by default, on for Kern County and the oil-gas sector page; ?wells=1|0), clustered, coloured by status, a red ring for a verified SB 1137 health-protection zone; a well click shows its CalGEM record. Region and near-me pages get an "Oil & gas wells" section: counts by status and HPZ, the schools and child-care centers with a well within 3,200 ft (about 92 Valley-wide, 75 in Kern), and on Kern County's page the share of Kern's permitted-facility ROG and benzene the oil & gas permit groupings report (2024: about 41% and 38%). Oil-gas facility pages say their point is an office. No join to CEIDARS (none exists).
Deploy: 1. `migrate` (Well). 2. One-off: `python manage.py import_wells` (14 requests to CalGEM's REST layer, about a minute). 3. The weekly task (Sundays 12:00 UTC) registers on the next `huey_primary` restart. The wells GeoJSON endpoint caches a day under a generation the import bumps.
```

---

## Self-review

- **Spec coverage, Phase 5.** `CountyNEI` with the spec's fields and unique key (Task 1); `import_nei --year 2023 [--sector-path] [--nonpoint-path]` streaming both zips row by row, NH3 and eight FIPS only, sector rows plus livestock subsector rows, one transaction, `SourceImport('nei', version='2023')`, manual cadence, no task (Task 1); "Ammonia (NH3)" in the criteria-side picker under a "Precursor" group in tons/yr, `stats.values()` reading `ToxicEmission`, map/list/sectors/Areas/region/near-me with no page code (Task 2); the facility page's Ammonia row with county and sector ranks (Task 2); the NEI bar replacing the CEPAM bar on county pages and the home page for the NH3 scope, with the year (Task 3); the county dairy pages' sixth tile (Task 3); the About section and the integrations entry (Task 3). Spec tests: filtering, subsector rows, idempotence, NH3 in the picker in tons, a facility row, the bar on a county page and its absence without rows, the dairy tile: Tasks 1–3.
- **Spec coverage, Phase 7.** `Well` with the spec's fields, the (county, status) index and the point's spatial index (a `PointField` gets one) (Task 4); `import_wells` paging the REST layer with the spec's `where` and `outFields`, upsert on `api`, deletion of rows not returned, `SourceImport('wellstar')`, the weekly `crontab(day_of_week='0', hour='12')` task (Task 4); no join to CEIDARS, regions by point (`well_q`), locations by distance (Task 5); the overlay checkbox (legend), off by default and on for Kern County's page and the oil-gas sector page, clustered circles by status with an HPZ ring, `GET /api/2.0/emissions/wells/geojson/` with `id, s, h`, cached a day, loaded only when on, the popup's fields and CalGEM link (Tasks 6–7); the region/near-me line and the schools list with the top ten (Task 7, in one block — decision 4); the Kern callout on Kern's page and the sector page (Tasks 5, 7); the oil-gas facility note (Task 7); About and integrations (Task 7). Spec tests: paging, upsert, removal, region counts by point, the 3,000/3,400 ft boundary, the GeoJSON shape and cache, the Kern arithmetic, the facility note, the smoke's overlay/cluster/well clicks: Tasks 4–8.
- **Placeholders.** Migration numbers (`0013`, `0014`) follow the chain; the implementer keeps what `makemigrations` produces. `nei.SECTOR_COLUMNS` / `NONPOINT_COLUMNS` and the three sector strings are checked against the real samples in Task 1 Step 2. Kern's page URL in the smoke script is built the way the script already builds Tulare's.
- **Type consistency.** `nei.context()` keys match `nei-context-bar.html`; `nei.dairy_tile()` keys match the tile; `wells.area_summary()` keys match the wells line; `schools_near_wells()` rows (`name`, `type_label`, `wells`) match the list; `kern_callout()` keys match `oil-gas-callout.html`; the GeoJSON's `s`/`h` match the JS paint expressions; `WellDetail`'s keys match `openWellPopup`; `facility_map_config`'s `wells_url` / `well_url` / `wells` / `wells_default` become `data-wells-url` / `data-well-url` / `data-wells` / `data-wells-default`, read as `wellsUrl` / `wellUrl` / `wells` / `wellsDefault`.
- **Decisions the implementer should not revisit** are listed under "Decisions made while planning"; each Review Focus line names its test.
