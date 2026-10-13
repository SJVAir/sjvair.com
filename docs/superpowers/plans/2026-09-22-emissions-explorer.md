# Facility Emissions Explorer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A public, database-driven explorer of permitted-facility emissions at `/tools/emissions/`, backed by a new `camp.apps.emissions` app that holds CARB's CEIDARS facility inventory and CEPAM county inventory and replaces `camp.apps.ceidars`.

**Architecture:** Server-rendered Django pages (vanilla views, htmx-boosted navigation) reusing the pesticides explorer's chrome, template tags, uPlot charts and MapTiler SDK bundle; a new small `facility-map.js` draws facilities as sized circles. Aggregates are computed per request from ~100k rows and cached per scope; no rollup tables. Air districts become `Region`s and every coverage decision reads from the database (county `Region`s, district `Region`s), never from SJV-specific constants.

**Tech Stack:** Django 5 + PostGIS, django-vanilla-views, django-resticus (API), django-sqids, htmx, uPlot, `@maptiler/sdk` (MapLibre GL), requests, pandas (CEIDARS CSV merge), PyYAML.

**Spec:** `docs/superpowers/specs/2026-09-22-emissions-explorer-design.md` (read it before starting any task).

## Global Constraints

- Work only in the worktree `/home/derek/dev/ccac/sjvair.com/.claude/worktrees/feature+ceidars-explorer` (branch `feature/ceidars-explorer`). Never edit the main checkout. After each commit, verify with `git -C /home/derek/dev/ccac/sjvair.com/.claude/worktrees/feature+ceidars-explorer log --oneline -1` that the commit landed on this branch.
- Run tests with this exact command (the main checkout's compose file, the worktree mounted over `/app`, a private test DB so other sessions can't collide):
  ```bash
  docker compose -f /home/derek/dev/ccac/sjvair.com/docker-compose.yml --project-directory /home/derek/dev/ccac/sjvair.com \
    run --rm -T -e DATABASE_URL=postgis://sjvair:changeme@db:5432/sjvair_emissions \
    -v /home/derek/dev/ccac/sjvair.com/.claude/worktrees/feature+ceidars-explorer:/app \
    test pytest <paths> -q -p no:cacheprovider --create-db
  ```
  Referred to below as `$TEST <paths>`. `fatal: not a git repository` in its output is harmless. Management commands (`makemigrations`) run the same way with `test python manage.py ...` in place of `test pytest ...`.
- `makemigrations` also proposes an unrelated `pesticides`/`commodities` AlterField drift that exists on main. Always name the app (`makemigrations regions`, `makemigrations emissions`) and never include that drift.
- Tests: `django.test.TestCase` classes, plain `assert` statements (never `self.assertX`), `pytest.raises` for exceptions, fixtures from `/fixtures/*.yaml`.
- Models: new models get `sqid = SqidsField(alphabet=shuffle_alphabet('app.Model'))`; verbose names are `_()` as the first positional argument (`models.FloatField(_('Label'), null=True)`); don't align `=` signs.
- Never `git add -A` or `git add .`; list files explicitly. Commits are local only: never push. Commit messages carry no AI-attribution trailer of any kind (no `Co-Authored-By`, no "Generated with").
- No SJV-specific names in models, importers, stats or views: counties come from `Region.objects.counties()` (the county `Region`s named by `settings.SJVAIR_COUNTIES`), CARB county numbers from each county Region's `metadata['ca_county_code']`, districts from `Region(type='air_district')`. SJV wording is allowed only in templates.
- CEIDARS has no facility-level PM2.5: CARB's `PMT` column is **total PM** and is stored as `pm` ("Total PM"). Never label facility data PM2.5.
- CEPAM values are **tons/day** as published; multiply by 365 only when comparing with CEIDARS tons/yr. Toxic air contaminants are stored in tons/yr and displayed in **lbs/yr** (× 2000).
- Import years: CEIDARS and CEPAM **2010–2024**.
- The explorer's public name is "Facility Emissions Explorer"; "CEIDARS"/"CEPAM" appear only on the About page and in source notes. Never link raw API endpoints from pages.
- Place pages, near-me, schools, clustering, heatmaps and enforcement data are out of scope.

## File Map

| Path | Responsibility | Task |
|---|---|---|
| `camp/apps/regions/models.py` | `Region.Type.AIR_DISTRICT` + category | 1 |
| `camp/apps/regions/air_districts.py` | Fetch/group CARB district features, read the district datafile | 1 |
| `camp/apps/regions/management/commands/import_air_districts.py` | Import districts intersecting covered counties | 1 |
| `datafiles/air-districts.yaml` | 35 districts: name, carb_url, complaints_url, phone (already on the branch, uncommitted) | 1 |
| `camp/apps/emissions/models.py` | `Facility`, `EmissionsRecord`, `CountyInventory` | 2, 3, 4 |
| `camp/apps/emissions/carb.py` | Covered counties → CARB county numbers; year-range parsing | 2 |
| `camp/apps/emissions/ceidars.py` | CEIDARS fetch/parse helpers | 2 |
| `camp/apps/emissions/management/commands/import_ceidars.py` | Facility inventory importer | 2 |
| `camp/apps/emissions/management/commands/ceidars_summary.py` | Console summary (moved) | 2 |
| `camp/apps/emissions/admin.py` | Admin (moved) | 2 |
| `camp/apps/ceidars/` | Shell: `apps.py`, empty `models.py`, migrations incl. `0002` delete | 2 |
| `camp/api/v2/emissions/` | API (moved from `camp/api/v2/ceidars/`), later geojson + search | 2, 8 |
| `fixtures/emissions.yaml` | Test fixture (replaces `fixtures/ceidars.yaml`) | 2 |
| `camp/apps/emissions/sectors.py` + `datafiles/sic-codes.csv` | SIC → sector, SIC titles | 3 |
| `camp/apps/emissions/management/commands/assign_sectors.py` | Re-apply sectors | 3 |
| `camp/apps/emissions/cepam.py` + `management/commands/import_cepam.py` | County inventory importer | 4 |
| `camp/apps/emissions/pollutants.py` | Pollutant registry | 5 |
| `camp/apps/emissions/stats.py` | Scope + aggregates | 5 |
| `camp/apps/emissions/views.py`, `urls.py`, `templatetags/emissions_explorer.py` | Pages | 6, 7 |
| `camp/templates/emissions/**` | Templates | 6, 7, 8 |
| `assets/sass/sjvair/pages/emissions.sass` | Page styles | 6 |
| `assets/js/emissions/facility-map.js` + `assets/css/emissions/facility-map.css` | Map | 8 |
| `scripts/emissions_map_smoke.py` | Manual headless smoke test | 8 |

Tests live in `camp/apps/emissions/tests/` (a package: `test_models.py`, `test_import_ceidars.py`, `test_sectors.py`, `test_cepam.py`, `test_stats.py`, `test_views.py`), `camp/apps/regions/tests/test_air_districts.py`, and `camp/api/v2/emissions/tests.py`.

---

### Task 1: Air districts as Regions

**Files:**
- Modify: `camp/apps/regions/models.py:29-34` (Type), `:70-74` (TYPE_CATEGORIES)
- Create: `camp/apps/regions/migrations/00NN_region_type_air_district.py` (generated)
- Create: `camp/apps/regions/air_districts.py`
- Create: `camp/apps/regions/management/commands/import_air_districts.py`
- Commit: `datafiles/air-districts.yaml` (already present on the branch)
- Test: `camp/apps/regions/tests/test_air_districts.py`

**Interfaces:**
- Produces: `Region.Type.AIR_DISTRICT == 'air_district'`; district Regions with `external_id` = CARB code (`'SJU'`, `'KER'`), `name` from the datafile (`'San Joaquin Valley APCD'`), `metadata = {'code', 'arcgis_name', 'carb_url', 'complaints_url', 'phone'}`. Later tasks look districts up with `Region.objects.filter(type=Region.Type.AIR_DISTRICT)` keyed by `external_id`.

- [ ] **Step 1: Write the failing tests**

Create `camp/apps/regions/tests/test_air_districts.py`:

```python
import json
from unittest.mock import MagicMock, patch

import pytest

from django.contrib.gis.geos import Polygon
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from camp.apps.regions import air_districts
from camp.apps.regions.models import Region


def square(x, y, size=0.1):
    """A small lon/lat square as a GeoJSON geometry dict."""
    return json.loads(Polygon.from_bbox((x, y, x + size, y + size)).geojson)


def feature(code, name, geometry):
    return {
        'type': 'Feature',
        'properties': {'Air_District_Code': code, 'Air_District_Name': name},
        'geometry': geometry,
    }


def response(features):
    mock = MagicMock()
    mock.json.return_value = {'type': 'FeatureCollection', 'features': features}
    mock.raise_for_status.return_value = None
    return mock


class GroupByCodeTests(TestCase):
    def test_multi_part_districts_are_unioned(self):
        grouped = air_districts.group_by_code([
            feature('SJU', 'SAN JOAQUIN VALLEY UNIFIED APCD', square(-120, 36)),
            feature('SJU', 'SAN JOAQUIN VALLEY UNIFIED APCD', square(-119, 36)),
            feature('KER', 'EASTERN KERN APCD', square(-118, 35)),
        ])
        assert set(grouped) == {'SJU', 'KER'}
        assert grouped['SJU']['name'] == 'SAN JOAQUIN VALLEY UNIFIED APCD'
        assert grouped['SJU']['geometry'].geom_type == 'MultiPolygon'
        assert len(grouped['SJU']['geometry']) == 2


class DirectoryTests(TestCase):
    def test_datafile_has_every_district_used_here(self):
        directory = air_districts.load_directory()
        assert directory['SJU']['name'] == 'San Joaquin Valley APCD'
        assert directory['KER']['name'] == 'Eastern Kern APCD'
        assert directory['SJU']['complaints_url'].startswith('https://')
        assert len(directory) == 35


class ImportAirDistrictsTests(TestCase):
    fixtures = ['regions.yaml']

    def setUp(self):
        fresno = Region.objects.get(type=Region.Type.COUNTY, slug='fresno')
        kern = Region.objects.get(type=Region.Type.COUNTY, slug='kern')
        # Districts drawn to lie inside the fixture's county boundaries, plus
        # one far outside every covered county.
        fresno_point = fresno.boundary.geometry.point_on_surface
        kern_point = kern.boundary.geometry.point_on_surface
        self.features = [
            feature('SJU', 'SAN JOAQUIN VALLEY UNIFIED APCD', square(fresno_point.x, fresno_point.y, 0.01)),
            feature('KER', 'EASTERN KERN APCD', square(kern_point.x, kern_point.y, 0.01)),
            feature('SC', 'SOUTH COAST AQMD', square(-117.5, 33.8)),
        ]

    def run_import(self):
        with patch('camp.apps.regions.air_districts.requests.get', return_value=response(self.features)):
            call_command('import_air_districts')

    def test_imports_only_districts_in_covered_counties(self):
        self.run_import()
        codes = set(Region.objects.filter(type=Region.Type.AIR_DISTRICT).values_list('external_id', flat=True))
        assert codes == {'SJU', 'KER'}

    def test_name_and_metadata_come_from_the_datafile(self):
        self.run_import()
        district = Region.objects.get(type=Region.Type.AIR_DISTRICT, external_id='KER')
        assert district.name == 'Eastern Kern APCD'
        assert district.slug == 'eastern-kern-apcd'
        assert district.metadata['code'] == 'KER'
        assert district.metadata['arcgis_name'] == 'EASTERN KERN APCD'
        assert district.metadata['phone'] == '(661) 862-5250'
        assert district.metadata['carb_url'].startswith('https://ww2.arb.ca.gov/')
        assert district.boundary is not None

    def test_code_missing_from_datafile_falls_back_to_title_cased_arcgis_name(self):
        with patch.object(air_districts, 'load_directory', return_value={}):
            self.run_import()
        district = Region.objects.get(type=Region.Type.AIR_DISTRICT, external_id='SJU')
        assert district.name == 'San Joaquin Valley Unified APCD'
        assert district.metadata['carb_url'] == ''

    def test_rerun_is_idempotent(self):
        self.run_import()
        self.run_import()
        assert Region.objects.filter(type=Region.Type.AIR_DISTRICT).count() == 2

    def test_no_county_regions_is_an_error(self):
        Region.objects.filter(type=Region.Type.COUNTY).delete()
        with pytest.raises(CommandError, match='import_counties'):
            self.run_import()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `$TEST camp/apps/regions/tests/test_air_districts.py`
Expected: FAIL/ERROR with `ImportError: cannot import name 'air_districts'`.

- [ ] **Step 3: Add the Region type**

In `camp/apps/regions/models.py`, under `# Governmental districts` add after `SCHOOL_DISTRICT`:

```python
        AIR_DISTRICT = 'air_district', _('Air District')
```

and in `TYPE_CATEGORIES` after `Type.SCHOOL_DISTRICT: Category.DISTRICT,`:

```python
        Type.AIR_DISTRICT: Category.DISTRICT,
```

Generate the migration: `docker compose ... test python manage.py makemigrations regions --name region_type_air_district` (same prefix as `$TEST`). It contains only an `AlterField` on `region.type` choices.

- [ ] **Step 4: Write the helpers**

Create `camp/apps/regions/air_districts.py`:

```python
"""
California air districts from CARB's "California Air District Boundaries"
layer, for `import_air_districts`.

The layer carries a code and an all-caps name per feature, and a district with
several parts comes as several features. Display names and contacts come from
`datafiles/air-districts.yaml`, captured from CARB's district directory, since
the layer has neither.
"""

import json

import requests

from django.contrib.gis.geos import GEOSGeometry, MultiPolygon

from camp.utils.datafiles import datafile

FEATURES_URL = (
    'https://services6.arcgis.com/x7ftScCDR8g2kVFB/arcgis/rest/services/'
    'Air_District_WFL1/FeatureServer/0/query'
)
FEATURES_PARAMS = {
    'where': '1=1',
    'outFields': 'Air_District_Code,Air_District_Name',
    'outSR': '4326',
    'f': 'geojson',
}
DIRECTORY_FILE = 'air-districts.yaml'
DIRECTORY_FIELDS = ('carb_url', 'complaints_url', 'phone')


def fetch_features():
    """Every district feature as GeoJSON (about 8 MB, 47 features for 35 districts)."""
    response = requests.get(FEATURES_URL, params=FEATURES_PARAMS, timeout=120)
    response.raise_for_status()
    return response.json()['features']


def _polygons(geometry):
    return list(geometry) if geometry.geom_type == 'MultiPolygon' else [geometry]


def group_by_code(features):
    """{code: {'name': <layer name>, 'geometry': MultiPolygon}}, one entry per district."""
    grouped = {}
    for item in features:
        props = item['properties']
        code = props['Air_District_Code']
        geometry = GEOSGeometry(json.dumps(item['geometry']), srid=4326)
        entry = grouped.setdefault(code, {'name': props['Air_District_Name'], 'polygons': []})
        entry['polygons'].extend(_polygons(geometry))
    return {
        code: {'name': entry['name'], 'geometry': MultiPolygon(*entry['polygons'], srid=4326)}
        for code, entry in grouped.items()
    }


def load_directory():
    """{code: {'name', 'carb_url', 'complaints_url', 'phone'}} from the datafile."""
    return datafile(DIRECTORY_FILE)


def title_case(name):
    """'SAN JOAQUIN VALLEY UNIFIED APCD' -> 'San Joaquin Valley Unified APCD'."""
    words = []
    for word in name.split():
        words.append(word if word in ('APCD', 'AQMD') else word.capitalize())
    return ' '.join(words)
```

- [ ] **Step 5: Write the command**

Create `camp/apps/regions/management/commands/import_air_districts.py`:

```python
from django.contrib.gis.db.models import Union
from django.core.management.base import BaseCommand, CommandError
from django.utils.text import slugify

from camp.apps.regions import air_districts
from camp.apps.regions.models import Region

# The layer has no published version; tie the Boundary version to when it
# was fetched, so a later refresh adds a version instead of overwriting.
GEOMETRY_VERSION = '2026-09-22'

# A district counts as covered when at least this share of its area lies in
# the covered counties. Districts that merely share a border with them only
# overlap by slivers where the two sources' lines disagree.
MIN_COVERED_SHARE = 0.01


class Command(BaseCommand):
    help = (
        'Import the CARB air districts that cover the counties in '
        'settings.SJVAIR_COUNTIES as Region(type=air_district) + Boundary records.'
    )

    def handle(self, *args, **options):
        coverage = Region.objects.counties().aggregate(area=Union('boundary__geometry'))['area']
        if coverage is None:
            raise CommandError('No county Regions with boundaries are loaded; run import_counties first.')

        directory = air_districts.load_directory()
        self.stdout.write('Fetching CARB air district boundaries...')
        districts = air_districts.group_by_code(air_districts.fetch_features())

        imported = 0
        for code, district in sorted(districts.items()):
            geometry = district['geometry']
            share = geometry.intersection(coverage).area / geometry.area if geometry.area else 0
            if share < MIN_COVERED_SHARE:
                continue

            entry = directory.get(code) or {}
            name = entry.get('name') or air_districts.title_case(district['name'])
            metadata = {
                'code': code,
                'arcgis_name': district['name'],
                **{field: entry.get(field, '') for field in air_districts.DIRECTORY_FIELDS},
            }
            region, created = Region.objects.import_or_update(
                name=name,
                slug=slugify(name),
                type=Region.Type.AIR_DISTRICT,
                external_id=code,
                geometry=geometry,
                version=GEOMETRY_VERSION,
                metadata=metadata,
            )
            imported += 1
            verb = 'Imported' if created else 'Updated'
            self.stdout.write(self.style.SUCCESS(f'{verb}: {region.name} ({code})'))

        self.stdout.write(f'{imported} air districts cover the configured counties.')
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `$TEST camp/apps/regions/tests/test_air_districts.py camp/apps/regions/tests/test_regions.py`
Expected: all PASS. (If `test_regions.py` checks that every `Region.Type` has a category, the `TYPE_CATEGORIES` entry keeps it green.)

- [ ] **Step 7: Commit**

```bash
git add camp/apps/regions/models.py camp/apps/regions/migrations/00*_region_type_air_district.py \
  camp/apps/regions/air_districts.py camp/apps/regions/management/commands/import_air_districts.py \
  camp/apps/regions/tests/test_air_districts.py datafiles/air-districts.yaml
git commit -m "feat(regions): import CARB air districts as Regions"
```

---
### Task 2: The `emissions` app replaces `ceidars`

Moves the CEIDARS models, importer, admin, summary command and API into `camp.apps.emissions` with a fresh schema: facilities keyed by `(county_code, air_district FK, facid)`, `pm25` renamed `pm`, counties read from the county Regions. `ceidars` shrinks to a shell whose last migration drops its tables.

The branch already carries **uncommitted** edits to `camp/apps/ceidars/` (whole-county importer keyed by `(DIS, FACID)`, an `air_basin`/`air_district` CharField pair, `ceidars/migrations/0002_facility_air_basin_district.py`, and tests). They are the starting point for the importer below; this task discards them from `ceidars` (no `air_basin` anywhere).

**Files:**
- Create: `camp/apps/emissions/__init__.py`, `apps.py`, `models.py`, `carb.py`, `ceidars.py`, `admin.py`, `migrations/__init__.py`, `migrations/0001_initial.py` (generated), `management/__init__.py`, `management/commands/__init__.py`, `management/commands/import_ceidars.py`, `management/commands/ceidars_summary.py`, `tests/__init__.py`, `tests/test_models.py`, `tests/test_import_ceidars.py`
- Create: `camp/api/v2/emissions/__init__.py`, `endpoints.py`, `filters.py`, `serializers.py`, `urls.py`, `tests.py`
- Create: `fixtures/emissions.yaml`
- Modify: `camp/settings/base.py:129` (INSTALLED_APPS), `camp/api/v2/urls.py:33`, `CLAUDE.md` (sqids convention line)
- Rewrite: `camp/apps/ceidars/models.py`; create `camp/apps/ceidars/migrations/0002_delete_models.py`
- Delete: `camp/apps/ceidars/admin.py`, `camp/apps/ceidars/tests.py`, `camp/apps/ceidars/management/`, `camp/apps/ceidars/migrations/0002_facility_air_basin_district.py` (untracked), `camp/api/v2/ceidars/`, `fixtures/ceidars.yaml`

**Interfaces:**
- Consumes: district Regions (`Region.Type.AIR_DISTRICT`, `external_id` = CARB code) from Task 1; county Regions' `metadata['ca_county_code']` (set by `import_counties`).
- Produces:
  - `Facility` fields `county_code:int, air_district:FK Region, facid:int, metadata_year, name, sic_code, address:dict, county/zipcode/city: FK Region|None, point`; manager methods `major_sources()`, `minor_sources()`; property `is_minor_source`; `get_county()`, `get_city()`, `get_zipcode()`, `geocode()`.
  - `EmissionsRecord` fields `facility, year, tog, rog, co, nox, sox, pm, pm10, total_score, hra, chindex, ahindex` + the 10 toxics; `related_name='emissions'`.
  - `MINOR_SOURCE_SIC_CODES` (frozenset) in `emissions.models`.
  - `carb.carb_counties(slug=None) -> list[tuple[int, Region]]` (raises `carb.CountyConfigError`), `carb.county_names() -> dict[int, str]`, `carb.parse_years(value: str) -> list[int]`.
  - `ceidars.fetch_county(year, county_code, on_error=None) -> tuple[DataFrame, dict]`, `ceidars.normalize_city`, `ceidars.decimal_or_none`, `ceidars.CRITERIA_COLS`, `ceidars.TOXICS_COLS`, `ceidars.TOXIC_POLLUTANTS`.
  - API namespace `api:v2:emissions` with `list`, `years`, `detail` (kwarg `facility_id`).
  - Fixture `emissions.yaml` (loaded after `regions.yaml`): district Regions pk 9001 `SJU`, 9002 `KER`; facilities pk 1 TEST PLANT (Fresno, SJU, SIC 3221), pk 2 TEST GAS STATION (Kern, SJU, SIC 5541), pk 3 TEST CEMENT (Kern, KER, SIC 3241); records for 2023 and 2024 as listed in Step 1.

- [ ] **Step 1: Write the fixture**

Create `fixtures/emissions.yaml` (`fixtures/regions.yaml` holds county pk 2 = Kern, 3 = Fresno, city pk 9 = Fresno, zipcode pk 11 = 93728):

```yaml
# Air districts (no boundaries needed for these tests)
- model: regions.region
  pk: 9001
  fields:
    created: 2024-01-01 00:00:00+00:00
    modified: 2024-01-01 00:00:00+00:00
    name: San Joaquin Valley APCD
    slug: san-joaquin-valley-apcd
    type: air_district
    external_id: SJU
    metadata: {"code": "SJU", "carb_url": "https://ww2.arb.ca.gov/san-joaquin-valley-air-pollution-control-district", "complaints_url": "https://ww2.valleyair.org/file-a-complaint", "phone": "(559) 230-6000"}
- model: regions.region
  pk: 9002
  fields:
    created: 2024-01-01 00:00:00+00:00
    modified: 2024-01-01 00:00:00+00:00
    name: Eastern Kern APCD
    slug: eastern-kern-apcd
    type: air_district
    external_id: KER
    metadata: {"code": "KER", "carb_url": "https://ww2.arb.ca.gov/eastern-kern-air-pollution-control-district", "complaints_url": "", "phone": "(661) 862-5250"}

# Facility 1: major source in Fresno
- model: emissions.facility
  pk: 1
  fields:
    created: 2024-01-01 00:00:00+00:00
    modified: 2024-01-01 00:00:00+00:00
    county_code: 10
    air_district: 9001
    facid: 1
    metadata_year: 2024
    name: TEST PLANT
    sic_code: 3221
    address: {"street": "123 MAIN ST", "city": "FRESNO", "zipcode": "93728"}
    point: SRID=4326;POINT (-119.787 36.737)
    county: 3
    city: 9
    zipcode: 11

# Facility 2: minor source (gas station) in Kern's valley portion
- model: emissions.facility
  pk: 2
  fields:
    created: 2024-01-01 00:00:00+00:00
    modified: 2024-01-01 00:00:00+00:00
    county_code: 15
    air_district: 9001
    facid: 2
    metadata_year: 2024
    name: TEST GAS STATION
    sic_code: 5541
    address: {"street": "456 OAK AVE", "city": "BAKERSFIELD", "zipcode": "93301"}
    point: SRID=4326;POINT (-119.018 35.373)
    county: 2
    city: null
    zipcode: null

# Facility 3: Eastern Kern cement plant (same county, other district)
- model: emissions.facility
  pk: 3
  fields:
    created: 2024-01-01 00:00:00+00:00
    modified: 2024-01-01 00:00:00+00:00
    county_code: 15
    air_district: 9002
    facid: 2
    metadata_year: 2024
    name: TEST CEMENT
    sic_code: 3241
    address: {"street": "1 QUARRY RD", "city": "MOJAVE", "zipcode": "93501"}
    point: SRID=4326;POINT (-118.17 35.05)
    county: 2
    city: null
    zipcode: null

- model: emissions.emissionsrecord
  pk: 1
  fields:
    created: 2024-01-01 00:00:00+00:00
    modified: 2024-01-01 00:00:00+00:00
    facility: 1
    year: 2023
    tog: "1.5"
    nox: "3.0"
    pm: "0.8"
    pm10: "0.5"
- model: emissions.emissionsrecord
  pk: 2
  fields:
    created: 2024-01-01 00:00:00+00:00
    modified: 2024-01-01 00:00:00+00:00
    facility: 2
    year: 2023
    tog: "0.1"
    rog: "0.1"
- model: emissions.emissionsrecord
  pk: 3
  fields:
    created: 2024-01-01 00:00:00+00:00
    modified: 2024-01-01 00:00:00+00:00
    facility: 1
    year: 2024
    nox: "6.0"
    pm: "1.0"
    pm10: "0.6"
    benzene: "0.001"
- model: emissions.emissionsrecord
  pk: 4
  fields:
    created: 2024-01-01 00:00:00+00:00
    modified: 2024-01-01 00:00:00+00:00
    facility: 3
    year: 2024
    nox: "100.0"
    pm: "20.0"
    pm10: "15.0"
- model: emissions.emissionsrecord
  pk: 5
  fields:
    created: 2024-01-01 00:00:00+00:00
    modified: 2024-01-01 00:00:00+00:00
    facility: 2
    year: 2024
    rog: "0.2"
```

Note facilities 2 and 3 share `county_code=15, facid=2` in different districts: the fixture itself exercises the identity rule.

- [ ] **Step 2: Write the failing model tests**

Create `camp/apps/emissions/tests/__init__.py` (empty) and `camp/apps/emissions/tests/test_models.py`:

```python
from unittest.mock import patch

import pytest

from django.contrib.gis.geos import Point
from django.db import IntegrityError, connection, transaction
from django.test import TestCase

from camp.apps.emissions.models import EmissionsRecord, Facility
from camp.apps.regions.models import Region


class FacilityTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def test_same_facid_in_two_districts_is_two_facilities(self):
        assert Facility.objects.filter(county_code=15, facid=2).count() == 2

    def test_county_district_facid_is_unique(self):
        sju = Region.objects.get(pk=9001)
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                Facility.objects.create(county_code=10, air_district=sju, facid=1, name='DUPLICATE')

    def test_district_is_protected(self):
        from django.db.models import ProtectedError
        with pytest.raises(ProtectedError):
            Region.objects.get(pk=9002).delete()

    def test_minor_sources(self):
        assert list(Facility.objects.minor_sources().values_list('name', flat=True)) == ['TEST GAS STATION']
        assert set(Facility.objects.major_sources().values_list('name', flat=True)) == {'TEST PLANT', 'TEST CEMENT'}
        assert Facility.objects.get(pk=2).is_minor_source

    def test_geocode_sets_point_without_saving(self):
        facility = Facility.objects.get(pk=2)
        point = Point(-119.0, 35.4, srid=4326)
        with patch('camp.utils.geocode.census', return_value=point):
            assert facility.geocode() is True
        assert facility.point == point
        facility.refresh_from_db()
        assert facility.point != point


class EmissionsRecordTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def test_total_pm_field(self):
        record = EmissionsRecord.objects.get(pk=3)
        assert float(record.pm) == 1.0
        assert not hasattr(record, 'pm25')

    def test_one_record_per_facility_year(self):
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                EmissionsRecord.objects.create(facility_id=1, year=2024)


class CeidarsTablesDroppedTests(TestCase):
    def test_ceidars_tables_are_gone(self):
        tables = connection.introspection.table_names()
        assert 'ceidars_facility' not in tables
        assert 'ceidars_emissionsrecord' not in tables
        assert 'emissions_facility' in tables
```

- [ ] **Step 3: Create the app and models**

`camp/apps/emissions/__init__.py`: empty. `camp/apps/emissions/apps.py`:

```python
from django.apps import AppConfig


class EmissionsConfig(AppConfig):
    name = 'camp.apps.emissions'
    verbose_name = 'Emissions'
```

`camp/apps/emissions/models.py`:

```python
from django.contrib.gis.db import models
from django.utils.translation import gettext_lazy as _

from django_sqids import SqidsField, shuffle_alphabet
from model_utils.models import TimeStampedModel

from camp.utils import geocode as _geocode


# SIC codes that CEIDARS excludes via the "all_fac=C" parameter -- gas stations,
# newspapers, print shops, dry cleaners, and autobody shops. These are minor
# permitted sources whose emissions are aggregated at the county level in CARB's
# areawide inventory rather than individually attributed.
MINOR_SOURCE_SIC_CODES = frozenset([
    2711,  # Newspapers
    2752,  # Commercial printing, lithographic
    5541,  # Gasoline service stations
    7216,  # Dry cleaning plants
    7532,  # Top, body & upholstery repair shops
    7538,  # Automotive repair shops, NEC
])


class FacilityQuerySet(models.QuerySet):
    def major_sources(self):
        return self.exclude(sic_code__in=MINOR_SOURCE_SIC_CODES)

    def minor_sources(self):
        return self.filter(sic_code__in=MINOR_SOURCE_SIC_CODES)


class FacilityManager(models.Manager):
    def get_queryset(self):
        return (
            FacilityQuerySet(self.model, using=self._db)
            .select_related('county', 'zipcode', 'city', 'air_district')
        )

    def major_sources(self):
        return self.get_queryset().major_sources()

    def minor_sources(self):
        return self.get_queryset().minor_sources()


class Facility(TimeStampedModel):
    """A permitted stationary source in CARB's CEIDARS facility inventory."""

    objects = FacilityManager()
    sqid = SqidsField(alphabet=shuffle_alphabet('emissions.Facility'))

    # CARB's county number (alphabetical, 1-58).
    county_code = models.IntegerField(_('County code'))
    # The air district that regulates the facility. Part of its identity:
    # districts assign FACIDs independently, so a FACID is only unique within
    # one. Taken from CARB's DIS code at import, never from the point (which
    # can be missing, or land on the wrong side of a district line).
    air_district = models.ForeignKey(
        'regions.Region',
        verbose_name=_('Air district'),
        on_delete=models.PROTECT,
        related_name='district_facilities',
        limit_choices_to={'type': 'air_district'},
    )
    facid = models.IntegerField(_('Facility ID'))

    # Tracks which import year last wrote the facility metadata (name, address,
    # sic_code, region FKs). Used to prevent older imports from overwriting
    # newer metadata -- emissions records are always upserted regardless.
    metadata_year = models.IntegerField(_('Metadata year'), null=True, blank=True)
    name = models.CharField(_('Name'), max_length=60)
    sic_code = models.IntegerField(_('SIC code'), null=True, blank=True)

    # Raw address fields from CEIDARS -- preserved as-is for reference.
    # City names in particular are noisy (typos, non-city strings, county
    # names) so matching against Region is handled separately via the FKs.
    address = models.JSONField(_('Address'), default=dict, blank=True)

    # Region FKs -- populated at import time from address data.
    # county is always set (the county being imported).
    # zipcode and city may be null for PO Box ZIPs (no ZCTA polygon exists)
    # or unresolvable city strings.
    county = models.ForeignKey(
        'regions.Region',
        verbose_name=_('County'),
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='county_facilities',
    )
    zipcode = models.ForeignKey(
        'regions.Region',
        verbose_name=_('Zipcode'),
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='zipcode_facilities',
    )
    city = models.ForeignKey(
        'regions.Region',
        verbose_name=_('City'),
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='city_facilities',
    )

    point = models.PointField(_('Point'), null=True, blank=True)

    class Meta:
        unique_together = [('county_code', 'air_district', 'facid')]
        verbose_name_plural = 'facilities'

    def __str__(self):
        return f'{self.name} ({self.address.get("city", "")})'

    def get_county(self):
        return self.county.name if self.county_id else None

    def get_city(self):
        return self.city.name if self.city_id else self.address.get('city', '')

    def get_zipcode(self):
        return self.zipcode.name if self.zipcode_id else self.address.get('zipcode', '')

    @property
    def is_minor_source(self):
        return self.sic_code in MINOR_SOURCE_SIC_CODES

    def geocode(self):
        """
        Geocodes the facility address, trying Census first then MapTiler.
        Sets self.point on success. Returns True/False. Does not save.
        """
        street = self.address.get('street', '')
        city = self.address.get('city', '')
        zipcode = self.address.get('zipcode', '')
        point = _geocode.resolve(f'{street}, {city}, CA {zipcode}')
        if point:
            self.point = point
            return True
        return False


class EmissionsRecord(TimeStampedModel):
    """One facility's CEIDARS emissions for one inventory year, in tons/yr."""

    sqid = SqidsField(alphabet=shuffle_alphabet('emissions.EmissionsRecord'))
    facility = models.ForeignKey(
        Facility,
        related_name='emissions',
        on_delete=models.CASCADE,
    )
    year = models.IntegerField(_('Year'))

    # Criteria pollutants (tons/yr). CARB's PMT column is total particulate
    # matter; CEIDARS has no facility-level PM2.5.
    tog = models.DecimalField(_('Total organic gases (tons/yr)'), max_digits=25, decimal_places=15, null=True, blank=True)
    rog = models.DecimalField(_('Reactive organic gases (tons/yr)'), max_digits=25, decimal_places=15, null=True, blank=True)
    co = models.DecimalField(_('Carbon monoxide (tons/yr)'), max_digits=25, decimal_places=15, null=True, blank=True)
    nox = models.DecimalField(_('Nitrogen oxides (tons/yr)'), max_digits=25, decimal_places=15, null=True, blank=True)
    sox = models.DecimalField(_('Sulfur oxides (tons/yr)'), max_digits=25, decimal_places=15, null=True, blank=True)
    pm = models.DecimalField(_('Total PM (tons/yr)'), max_digits=25, decimal_places=15, null=True, blank=True)
    pm10 = models.DecimalField(_('PM10 (tons/yr)'), max_digits=25, decimal_places=15, null=True, blank=True)

    # Toxics summary (blank for all SJV facilities in current CARB exports; kept, not displayed)
    total_score = models.DecimalField(_('Total toxics score'), max_digits=10, decimal_places=2, null=True, blank=True)
    hra = models.DecimalField(_('Health risk assessment'), max_digits=10, decimal_places=2, null=True, blank=True)
    chindex = models.DecimalField(_('Cancer health index'), max_digits=10, decimal_places=2, null=True, blank=True)
    ahindex = models.DecimalField(_('Acute health index'), max_digits=10, decimal_places=2, null=True, blank=True)

    # Named toxic air contaminants (tons/yr; the explorer shows lbs/yr)
    acetaldehyde = models.DecimalField(_('Acetaldehyde (tons/yr)'), max_digits=25, decimal_places=15, null=True, blank=True)
    benzene = models.DecimalField(_('Benzene (tons/yr)'), max_digits=25, decimal_places=15, null=True, blank=True)
    butadiene = models.DecimalField(_('1,3-Butadiene (tons/yr)'), max_digits=25, decimal_places=15, null=True, blank=True)
    carbon_tetrachloride = models.DecimalField(_('Carbon tetrachloride (tons/yr)'), max_digits=25, decimal_places=15, null=True, blank=True)
    chromium_hexavalent = models.DecimalField(_('Chromium hexavalent (tons/yr)'), max_digits=25, decimal_places=15, null=True, blank=True)
    dichlorobenzene = models.DecimalField(_('para-Dichlorobenzene (tons/yr)'), max_digits=25, decimal_places=15, null=True, blank=True)
    formaldehyde = models.DecimalField(_('Formaldehyde (tons/yr)'), max_digits=25, decimal_places=15, null=True, blank=True)
    methylene_chloride = models.DecimalField(_('Methylene chloride (tons/yr)'), max_digits=25, decimal_places=15, null=True, blank=True)
    naphthalene = models.DecimalField(_('Naphthalene (tons/yr)'), max_digits=25, decimal_places=15, null=True, blank=True)
    perchloroethylene = models.DecimalField(_('Perchloroethylene (tons/yr)'), max_digits=25, decimal_places=15, null=True, blank=True)

    class Meta:
        unique_together = [('facility', 'year')]

    def __str__(self):
        return f'{self.facility.name} ({self.year})'
```

Add `'camp.apps.emissions',` to `INSTALLED_APPS` in `camp/settings/base.py` directly after `'camp.apps.ceidars',`, then generate: `... test python manage.py makemigrations emissions` → `camp/apps/emissions/migrations/0001_initial.py` (its dependencies include the latest `regions` migration from Task 1).

- [ ] **Step 4: Reduce `ceidars` to a shell that drops its tables**

```bash
git rm -q camp/apps/ceidars/admin.py camp/apps/ceidars/tests.py
git rm -rq camp/apps/ceidars/management
rm -f camp/apps/ceidars/migrations/0002_facility_air_basin_district.py
git rm -q fixtures/ceidars.yaml
```

(`git rm` on files with uncommitted edits needs `-f`; use `git rm -qf` if it refuses.)

Rewrite `camp/apps/ceidars/models.py` to only:

```python
# The CEIDARS models moved to camp.apps.emissions. This app stays installed
# only so its migrations run, the last of which drops its tables; delete the
# app once every environment has applied ceidars 0002.
```

Create `camp/apps/ceidars/migrations/0002_delete_models.py`:

```python
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('ceidars', '0001_initial'),
    ]

    # Drops the old tables; the data is re-imported into camp.apps.emissions.
    operations = [
        migrations.DeleteModel(name='EmissionsRecord'),
        migrations.DeleteModel(name='Facility'),
    ]
```

- [ ] **Step 5: Run the model tests**

Run: `$TEST camp/apps/emissions/tests/test_models.py`
Expected: PASS (7 tests). Then confirm the schema is settled: `... test python manage.py makemigrations emissions ceidars --check --dry-run` prints `No changes detected`.

- [ ] **Step 6: Write the failing importer tests**

Create `camp/apps/emissions/tests/test_import_ceidars.py`:

```python
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from django.contrib.gis.geos import Point
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from camp.apps.emissions.ceidars import normalize_city
from camp.apps.emissions.models import EmissionsRecord, Facility
from camp.apps.regions.models import Region

CA_COUNTY_CODES = {
    'Fresno County': '10', 'Kern County': '15', 'Kings County': '16', 'Madera County': '20',
    'Merced County': '24', 'San Joaquin County': '39', 'Stanislaus County': '50', 'Tulare County': '54',
}

HEADER = 'CO,AB,FACID,DIS,FNAME,FSTREET,FCITY,FZIP,FSIC,COID,DISN,CHAPIS,CERR_CODE,TOGT,ROGT,COT,NOXT,SOXT,PMT,PM10T\n'
TOX_HEADER = 'CO,AB,FACID,DIS,FNAME,FSTREET,FCITY,FZIP,FSIC,COID,TS,HRA,CHINDEX,AHINDEX,DISN,CHAPIS,CERR_CODE\n'

FRESNO_CRITERIA = HEADER + '10,SJV,1,SJU,TEST FACILITY A,123 MAIN ST,FRESNO,93701,4911,FRE,SAN JOAQUIN VALLEY APCD,,,1.5,1.2,0.3,2.1,0.1,0.8,1.0\n'
FRESNO_TOXICS = TOX_HEADER + '10,SJV,1,SJU,TEST FACILITY A,123 MAIN ST,FRESNO,93701,4911,FRE,,,,,SAN JOAQUIN VALLEY APCD,,\n'

KERN_CRITERIA = HEADER + (
    '15,SJV,1,SJU,VALLEY HOSPITAL,2215 TRUXTUN AVE,BAKERSFIELD,93301,8062,KER,SAN JOAQUIN VALLEY APCD,,,1.0,1.0,1.0,1.0,1.0,1.0,1.0\n'
    '15,MD,1,KER,DESERT QUARRY,7037 TROTTER AVE,MOJAVE,93501,1422,KER,EASTERN KERN APCD,,,2.0,2.0,2.0,2.0,2.0,2.0,2.0\n'
)
KERN_TOXICS = TOX_HEADER + (
    '15,SJV,1,SJU,VALLEY HOSPITAL,2215 TRUXTUN AVE,BAKERSFIELD,93301,8062,KER,,,,,SAN JOAQUIN VALLEY APCD,,\n'
    '15,MD,1,KER,DESERT QUARRY,7037 TROTTER AVE,MOJAVE,93501,1422,KER,,,,,EASTERN KERN APCD,,\n'
)
KERN_BENZENE = TOX_HEADER.rstrip('\n') + ',EMS\n' + '15,MD,1,KER,DESERT QUARRY,7037 TROTTER AVE,MOJAVE,93501,1422,KER,,,,,EASTERN KERN APCD,,,0.25\n'

POINT = Point(-119.787, 36.737, srid=4326)


def carb(criteria_by_county, toxics_by_county, pollutants=None, urls=None):
    """A requests.get stand-in serving CARB CSVs by county code (`co_=`) and pollutant (`showpol=`)."""
    pollutants = pollutants or {}

    def get(url, **kwargs):
        if urls is not None:
            urls.append(url)
        county = int(url.split('co_=')[1].split('&')[0])
        cas_id = url.partition('showpol=')[2]
        mock = MagicMock()
        mock.raise_for_status.return_value = None
        if 'faccrit' in url:
            mock.text = criteria_by_county.get(county, '')
        elif cas_id:
            mock.text = pollutants.get((county, cas_id), toxics_by_county.get(county, ''))
        else:
            mock.text = toxics_by_county.get(county, '')
        return mock
    return get


def geocode_all(addresses, **kwargs):
    return [(address, POINT) for address in addresses]


class ImportCeidarsTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        # Start from no facilities: the fixture is here for its district Regions.
        EmissionsRecord.objects.all().delete()
        Facility.objects.all().delete()
        for county in Region.objects.counties():
            county.metadata['ca_county_code'] = CA_COUNTY_CODES[county.name]
            county.save(update_fields=['metadata'])

    def run_import(self, year=2024, county=None, criteria=None, toxics=None, pollutants=None, urls=None, geocode=geocode_all):
        criteria = criteria if criteria is not None else {10: FRESNO_CRITERIA, 15: KERN_CRITERIA}
        toxics = toxics if toxics is not None else {10: FRESNO_TOXICS, 15: KERN_TOXICS}
        with patch('requests.get', side_effect=carb(criteria, toxics, pollutants, urls)):
            with patch('camp.utils.geocode.resolve_batch', side_effect=geocode):
                kwargs = {'year': year}
                if county:
                    kwargs['county'] = county
                call_command('import_ceidars', **kwargs)

    def test_creates_facility_and_record(self):
        self.run_import(county='fresno')
        facility = Facility.objects.get(county_code=10, facid=1)
        assert facility.name == 'TEST FACILITY A'
        assert facility.air_district.external_id == 'SJU'
        assert facility.county.name == 'Fresno County'
        assert facility.point == POINT
        record = facility.emissions.get(year=2024)
        assert record.tog == Decimal('1.5')
        assert record.pm == Decimal('0.8')
        assert record.pm10 == Decimal('1.0')

    def test_requests_whole_counties(self):
        urls = []
        self.run_import(county='kern', urls=urls)
        assert urls
        for url in urls:
            assert 'co_=15' in url
            assert 'ab_=' not in url
            assert 'dis_=' not in url

    def test_covers_every_county_region_by_default(self):
        urls = []
        self.run_import(urls=urls)
        requested = {int(url.split('co_=')[1].split('&')[0]) for url in urls}
        expected = {int(county.metadata['ca_county_code']) for county in Region.objects.counties()}
        assert expected
        assert requested == expected

    def test_same_facid_in_two_districts(self):
        self.run_import(county='kern')
        valley = Facility.objects.get(county_code=15, air_district__external_id='SJU', facid=1)
        desert = Facility.objects.get(county_code=15, air_district__external_id='KER', facid=1)
        assert valley.name == 'VALLEY HOSPITAL'
        assert desert.name == 'DESERT QUARRY'
        assert valley.emissions.get(year=2024).nox == Decimal('1.0')
        assert desert.emissions.get(year=2024).nox == Decimal('2.0')

    def test_toxics_land_on_the_right_district(self):
        self.run_import(county='kern', pollutants={(15, '71432'): KERN_BENZENE})
        valley = Facility.objects.get(air_district__external_id='SJU', facid=1, county_code=15)
        desert = Facility.objects.get(air_district__external_id='KER', facid=1, county_code=15)
        assert valley.emissions.get(year=2024).benzene is None
        assert desert.emissions.get(year=2024).benzene == Decimal('0.25')

    def test_rerun_is_idempotent(self):
        self.run_import(county='kern')
        self.run_import(county='kern')
        assert Facility.objects.count() == 2
        assert EmissionsRecord.objects.count() == 2

    def test_older_year_does_not_overwrite_newer_metadata(self):
        self.run_import(county='fresno', year=2024)
        older = {10: FRESNO_CRITERIA.replace('TEST FACILITY A', 'OLD NAME')}
        self.run_import(county='fresno', year=2023, criteria=older)
        facility = Facility.objects.get(county_code=10, facid=1)
        assert facility.name == 'TEST FACILITY A'
        assert facility.metadata_year == 2024
        assert facility.emissions.count() == 2

    def test_geocode_failure_does_not_abort(self):
        self.run_import(county='fresno', geocode=lambda addresses, **kw: [(a, None) for a in addresses])
        facility = Facility.objects.get(county_code=10, facid=1)
        assert facility.point is None
        assert facility.emissions.count() == 1

    def test_unknown_district_fails_that_county_and_writes_nothing(self):
        Facility.objects.filter(air_district__external_id='KER').delete()
        Region.objects.filter(external_id='KER', type=Region.Type.AIR_DISTRICT).delete()
        with pytest.raises(CommandError, match='Kern County'):
            self.run_import()
        assert not Facility.objects.filter(county_code=15).exists()
        assert Facility.objects.filter(county_code=10).exists()

    def test_county_without_carb_code_is_an_error(self):
        fresno = Region.objects.get(type=Region.Type.COUNTY, slug='fresno')
        fresno.metadata.pop('ca_county_code')
        fresno.save(update_fields=['metadata'])
        with pytest.raises(CommandError, match='import_counties'):
            self.run_import(county='fresno')

    def test_unknown_county_slug_is_an_error(self):
        with pytest.raises(CommandError, match='nowhere'):
            self.run_import(county='nowhere')


class NormalizeCityTests(TestCase):
    def lookup(self, *names):
        return {name.upper(): name for name in names}

    def test_clean_match(self):
        assert normalize_city('FRESNO', self.lookup('Fresno')) == 'Fresno'

    def test_strips_ca_suffix(self):
        lookup = self.lookup('Bakersfield')
        assert normalize_city('BAKERSFIELD CA', lookup) == 'Bakersfield'
        assert normalize_city('BAKERSFIELD, CA', lookup) == 'Bakersfield'

    def test_applies_corrections(self):
        lookup = self.lookup('Porterville', 'McFarland', "O'Neals", 'Kettleman City')
        assert normalize_city('PORTERVILE', lookup) == 'Porterville'
        assert normalize_city('MC FARLAND', lookup) == 'McFarland'
        assert normalize_city('ONEALS', lookup) == "O'Neals"
        assert normalize_city('KETTLEMAN', lookup) == 'Kettleman City'

    def test_non_city_strings_return_none(self):
        lookup = self.lookup('Fresno')
        for value in ('FRESNO COUNTY', 'SJVAPCD', 'SEC 13 R27S R34E', 'W/O TAFT', 'SITE NEAR SANGER'):
            assert normalize_city(value, lookup) is None

    def test_empty_or_unmatched_returns_none(self):
        assert normalize_city('', {}) is None
        assert normalize_city('FRESNO', {}) is None
```

Run: `$TEST camp/apps/emissions/tests/test_import_ceidars.py`
Expected: FAIL/ERROR (`No module named 'camp.apps.emissions.ceidars'` / `Unknown command: 'import_ceidars'`).

- [ ] **Step 7: Write `carb.py` and `ceidars.py`**

`camp/apps/emissions/carb.py`:

```python
"""
The counties this deployment covers, as CARB knows them.

CARB numbers California's counties alphabetically (Alameda = 1 ... Yuba = 58).
`import_counties` stores that number on each county Region as
`metadata['ca_county_code']`, so coverage is whatever county Regions are
loaded for `settings.SJVAIR_COUNTIES` -- nothing here names a county.
"""

from camp.apps.regions.models import Region


class CountyConfigError(Exception):
    pass


def carb_counties(slug=None):
    """[(carb_county_number, county Region), ...] in name order, optionally one county by slug."""
    counties = Region.objects.counties().order_by('name')
    if slug:
        counties = counties.filter(slug=slug)
        if not counties:
            raise CountyConfigError(f'No covered county with slug {slug!r}.')
    result = []
    for county in counties:
        code = (county.metadata or {}).get('ca_county_code')
        if not code:
            raise CountyConfigError(
                f"{county.name} has no ca_county_code in its metadata; re-run import_counties."
            )
        result.append((int(code), county))
    if not result:
        raise CountyConfigError('No county Regions are loaded; run import_counties.')
    return result


def county_names():
    """{carb_county_number: county name} for the covered counties."""
    return {code: county.name for code, county in carb_counties()}


def parse_years(value):
    """'2024' -> [2024]; '2010-2024' -> [2010, ..., 2024]."""
    value = str(value).strip()
    if '-' in value:
        start, end = (int(part) for part in value.split('-', 1))
        if start > end:
            raise ValueError(f'Year range {value!r} runs backwards.')
        return list(range(start, end + 1))
    return [int(value)]
```

`camp/apps/emissions/ceidars.py` — the fetch/parse helpers, moved out of the command:

```python
"""
Fetching and parsing CARB's CEIDARS facility inventory CSVs.

No air basin or district filter in the URLs: a request returns the whole
county, so a county that spans two districts (Kern: SJU and KER) comes back
complete. Districts assign FACIDs independently, so rows are identified by
(DIS, FACID) everywhere below.
"""

import io
import re
import time

import pandas as pd
import requests

BASE_URL = 'https://www.arb.ca.gov/app/emsinv/iframe/facinfo'

# CARB column -> EmissionsRecord field. PMT is total particulate matter.
CRITERIA_COLS = {
    'TOGT': 'tog', 'ROGT': 'rog', 'COT': 'co',
    'NOXT': 'nox', 'SOXT': 'sox', 'PMT': 'pm', 'PM10T': 'pm10',
}

TOXICS_COLS = {
    'TS': 'total_score', 'HRA': 'hra',
    'CHINDEX': 'chindex', 'AHINDEX': 'ahindex',
}

# CAS number -> EmissionsRecord field name for named toxic air contaminants.
TOXIC_POLLUTANTS = {
    '75070': 'acetaldehyde',
    '71432': 'benzene',
    '106990': 'butadiene',
    '56235': 'carbon_tetrachloride',
    '18540299': 'chromium_hexavalent',
    '106467': 'dichlorobenzene',
    '50000': 'formaldehyde',
    '75092': 'methylene_chloride',
    '91203': 'naphthalene',
    '127184': 'perchloroethylene',
}

MERGE_KEYS = ['CO', 'AB', 'FACID', 'DIS', 'FNAME', 'FSTREET', 'FCITY', 'FZIP', 'FSIC']

# Known corrections for CEIDARS city name variants.
# Keys are uppercase raw values; values are the corrected uppercase form
# used for region lookup. Strip-CA-suffix handling is done separately.
CITY_CORRECTIONS = {
    'AWAHNEE': 'AHWAHNEE',
    'BAKERSIFLED': 'BAKERSFIELD',
    'KETTLEMAN': 'KETTLEMAN CITY',
    'LAKE OF THE WDS': 'LAKE OF THE WOODS',
    'LEGRAND': 'LE GRAND',
    'LEMONCOVE': 'LEMON COVE',
    'MC FARLAND': 'MCFARLAND',
    "O'NEILS": "O'NEALS",
    'ONEALS': "O'NEALS",
    'PINE MTN CLUB': 'PINE MOUNTAIN CLUB',
    'PORTERVILE': 'PORTERVILLE',
    'TRANQUILITY': 'TRANQUILLITY',
}

# Patterns that indicate a value is not a city name (county strings,
# GPS coordinates, descriptive strings, etc.) -- these resolve to None.
_NON_CITY_RE = re.compile(
    r'county|sjvapcd|valley$|national|nat park|\bnf\b|cyn\b|site near|'
    r'mi n/o|w/o\s|west of|skyline|tejon ranch|terminus|pampa peak|'
    r'las yeguas|western fresno|& kings|sec\s*\d|\bt\d+s\b',
    re.IGNORECASE,
)

_STRIP_CA_RE = re.compile(r',?\s*CA$', re.IGNORECASE)


def normalize_city(raw, city_lookup):
    """
    Normalize a raw CEIDARS city string and return a matching Region or None.

    city_lookup: dict mapping uppercase city/CDP name -> Region object.
    """
    city = _STRIP_CA_RE.sub('', raw.strip()).strip().upper()
    if not city or _NON_CITY_RE.search(city):
        return None
    city = CITY_CORRECTIONS.get(city, city)
    return city_lookup.get(city)


def csv_url(kind, year, county_code, cas_id=None):
    """kind is 'faccrit' (criteria) or 'factox' (toxics)."""
    url = f'{BASE_URL}/{kind}_output.csv?dbyr={year}&co_={county_code}'
    if cas_id:
        url += f'&showpol={cas_id}'
    return url


def fetch_csv(url, retries=5):
    for attempt in range(retries):
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            try:
                return pd.read_csv(io.StringIO(response.text), dtype=str).fillna('')
            except pd.errors.EmptyDataError:
                return pd.DataFrame()
        except requests.RequestException:
            if attempt == retries - 1:
                raise
            time.sleep((2 ** attempt) * 0.5)


def decimal_or_none(val):
    val = str(val).strip()
    if not val or val.lower() == 'nan':
        return None
    return val


def fetch_county(year, county_code, on_error=None):
    """
    (merged, toxic_ems) for one county and year.

    merged: the criteria and toxics CSVs outer-joined on the facility columns
    (an empty DataFrame when CARB has nothing). toxic_ems: {(DIS, FACID):
    {field: tons}} from the per-pollutant requests; a failed pollutant request
    is reported through on_error(field_name, exc) and skipped. Raises
    requests.RequestException if the criteria or toxics request fails.
    """
    criteria = fetch_csv(csv_url('faccrit', year, county_code))
    toxics = fetch_csv(csv_url('factox', year, county_code))

    toxic_ems = {}
    for cas_id, field_name in TOXIC_POLLUTANTS.items():
        try:
            pollutant = fetch_csv(csv_url('factox', year, county_code, cas_id))
        except requests.RequestException as exc:
            if on_error:
                on_error(field_name, exc)
            continue
        for _, row in pollutant.iterrows():
            key = (row['DIS'], int(row['FACID']))
            toxic_ems.setdefault(key, {})[field_name] = decimal_or_none(row.get('EMS', ''))

    frames = [frame for frame in (criteria, toxics) if not frame.empty]
    if not frames:
        merged = pd.DataFrame()
    elif len(frames) == 1:
        merged = frames[0]
    else:
        merged = pd.merge(
            criteria, toxics,
            on=MERGE_KEYS,
            how='outer',
            suffixes=('_crit', '_tox'),
        ).fillna('')
    return merged, toxic_ems
```

- [ ] **Step 8: Write the importer command**

Create the empty `camp/apps/emissions/management/__init__.py` and `camp/apps/emissions/management/commands/__init__.py`, then `camp/apps/emissions/management/commands/import_ceidars.py`:

```python
import time

import requests

from django.core.management.base import BaseCommand, CommandError

from camp.apps.emissions import carb, ceidars
from camp.apps.emissions.models import EmissionsRecord, Facility
from camp.apps.regions.models import Region
from camp.utils import geocode


class Command(BaseCommand):
    help = 'Import CEIDARS facility emissions for the covered counties and one inventory year.'

    def status(self, msg):
        """Write an overwriting status line, clearing any leftover characters."""
        self.stdout.write(f'{msg}\033[K', ending='\r')

    def add_arguments(self, parser):
        parser.add_argument('--year', type=int, required=True, help='Inventory year (e.g. 2024)')
        parser.add_argument('--county', help='Limit to one covered county, by slug (e.g. fresno)')
        parser.add_argument('--regeocode', action='store_true', help='Re-geocode all facilities, not just new ones')

    def handle(self, *args, **options):
        year = options['year']
        regeocode = options['regeocode']
        try:
            counties = carb.carb_counties(options.get('county'))
        except carb.CountyConfigError as exc:
            raise CommandError(str(exc))

        # Pre-load region lookups once for the entire import.
        districts = {
            region.external_id: region
            for region in Region.objects.filter(type=Region.Type.AIR_DISTRICT)
        }
        zipcode_regions = {r.name: r for r in Region.objects.filter(type=Region.Type.ZIPCODE)}
        city_regions = {
            r.name.upper(): r
            for r in Region.objects.filter(type__in=[Region.Type.CITY, Region.Type.CDP])
        }

        total_facilities = total_records = total_geocode_failures = 0
        failed = []
        start_time = time.monotonic()

        for county_code, county in counties:
            label = f'{county.name} ({county_code})'
            created_count = updated_count = record_count = geocode_failures = 0
            county_start = time.monotonic()

            self.status(f'{label}: fetching...')
            try:
                merged, toxic_ems = ceidars.fetch_county(
                    year, county_code,
                    on_error=lambda field, exc: self.stderr.write(f'{label}: {field} fetch failed -- {exc}'),
                )
            except requests.RequestException as exc:
                self.stderr.write(f'{label}: fetch failed -- {exc}')
                failed.append(county.name)
                continue

            if merged.empty:
                self.stdout.write(f'{label}: no facilities for {year}')
                continue

            # Every row's district must already exist as a Region: the FK is
            # part of the facility's identity. Write nothing for this county
            # rather than guess.
            unknown = sorted(set(merged['DIS']) - set(districts))
            if unknown:
                self.stderr.write(
                    f'{label}: no air district Region for {", ".join(unknown)}; '
                    f'run import_air_districts first. Nothing written for this county.'
                )
                failed.append(county.name)
                continue

            # Determine which facilities need geocoding.
            all_facids = [int(row['FACID']) for _, row in merged.iterrows()]
            existing_keys = set(
                Facility.objects.filter(county_code=county_code, facid__in=all_facids)
                .values_list('air_district__external_id', 'facid')
            )

            geocode_index = []  # [((district, facid), address_dict), ...] in batch order
            for _, row in merged.iterrows():
                key = (row['DIS'], int(row['FACID']))
                if key not in existing_keys or regeocode:
                    geocode_index.append((key, {
                        'street': row.get('FSTREET', '').strip(),
                        'city': row.get('FCITY', '').strip(),
                        'state': 'CA',
                        'zipcode': row.get('FZIP', '').strip(),
                    }))

            # Batch geocode upfront via Census, falling back to MapTiler for failures.
            positions = {}
            if geocode_index:
                self.status(f'{label}: geocoding {len(geocode_index)} facilities...')
                addr_to_key = {id(addr): key for key, addr in geocode_index}
                for addr, point in geocode.resolve_batch([addr for _, addr in geocode_index]):
                    positions[addr_to_key[id(addr)]] = point

            total_rows = len(merged)
            seen_keys = set()
            for i, (_, row) in enumerate(merged.iterrows(), 1):
                self.status(f'{label}: {i}/{total_rows} facilities...')
                district = row['DIS']
                facid = int(row['FACID'])
                key = (district, facid)
                if key in seen_keys:
                    continue
                seen_keys.add(key)

                address = {
                    'street': row.get('FSTREET', '').strip(),
                    'city': row.get('FCITY', '').strip(),
                    'zipcode': row.get('FZIP', '').strip(),
                }
                zipcode_region = zipcode_regions.get(address['zipcode'])
                city_region = ceidars.normalize_city(address['city'], city_regions)
                sic_code = int(row['FSIC']) if row.get('FSIC') else None

                facility, created = Facility.objects.get_or_create(
                    county_code=county_code,
                    air_district=districts[district],
                    facid=facid,
                    defaults={
                        'name': row.get('FNAME', '').strip(),
                        'address': address,
                        'sic_code': sic_code,
                        'metadata_year': year,
                        'county': county,
                        'zipcode': zipcode_region,
                        'city': city_region,
                    },
                )

                if created:
                    created_count += 1
                    facility.point = positions.get(key)
                    if facility.point is None:
                        geocode_failures += 1
                    facility.save()
                else:
                    updated_count += 1
                    if regeocode:
                        facility.point = positions.get(key)
                        if facility.point is None:
                            geocode_failures += 1

                    if facility.metadata_year is None or year >= facility.metadata_year:
                        facility.name = row.get('FNAME', '').strip()
                        facility.address = address
                        facility.sic_code = sic_code
                        facility.metadata_year = year
                        facility.county = county
                        facility.zipcode = zipcode_region
                        facility.city = city_region

                    facility.save()

                emissions_data = {
                    col: ceidars.decimal_or_none(row.get(src))
                    for src, col in ceidars.CRITERIA_COLS.items()
                }
                emissions_data.update({
                    col: ceidars.decimal_or_none(row.get(src))
                    for src, col in ceidars.TOXICS_COLS.items()
                })
                emissions_data.update(toxic_ems.get(key, {}))

                if all(v is None for v in emissions_data.values()):
                    continue

                EmissionsRecord.objects.update_or_create(
                    facility=facility,
                    year=year,
                    defaults=emissions_data,
                )
                record_count += 1

            elapsed = time.monotonic() - county_start
            self.stdout.write(
                f'{label}: '
                f'{created_count + updated_count} facilities '
                f'({created_count} new, {updated_count} updated), '
                f'{record_count} emissions records upserted, '
                f'{geocode_failures} geocoding failures '
                f'[{elapsed:.1f}s]'
            )

            total_facilities += created_count + updated_count
            total_records += record_count
            total_geocode_failures += geocode_failures

        total_elapsed = time.monotonic() - start_time
        self.stdout.write(
            f'\nDone. {total_facilities} facilities, '
            f'{total_records} emissions records, '
            f'{total_geocode_failures} geocoding failures '
            f'[{total_elapsed:.1f}s]'
        )
        if failed:
            raise CommandError(f'Import incomplete for: {", ".join(failed)}')
```

- [ ] **Step 9: Run the importer tests**

Run: `$TEST camp/apps/emissions/tests/`
Expected: all PASS.

- [ ] **Step 10: Move the summary command and admin**

`camp/apps/emissions/management/commands/ceidars_summary.py`: recreate from the deleted `camp/apps/ceidars/management/commands/ceidars_summary.py` (`git show HEAD:camp/apps/ceidars/management/commands/ceidars_summary.py`) with these changes only:
- imports: `from camp.apps.emissions import carb` and `from camp.apps.emissions.models import EmissionsRecord, Facility`; drop the `COUNTY_CODES` import and the `COUNTY_NAMES` constant.
- `CRITERIA_FIELDS = ['tog', 'rog', 'co', 'nox', 'sox', 'pm', 'pm10']`.
- `--county` becomes `parser.add_argument('--county', help='County slug (e.g. fresno)')`; in `handle`, resolve it with
  ```python
  names = carb.county_names()
  if county:
      try:
          county = carb.carb_counties(county)[0][0]
      except carb.CountyConfigError as exc:
          raise CommandError(str(exc))
  ```
  and replace every `COUNTY_CODES.get(code, "?")` / `COUNTY_CODES[county]` with `names.get(code, "?")` / `names[county]`.

`camp/apps/emissions/admin.py`: recreate from `git show HEAD:camp/apps/ceidars/admin.py` with these changes only:
- `EmissionsRecordInline.ALL_FIELDS`: `'pm25'` → `'pm'`.
- `FacilityAdmin.list_display` gains `'air_district'` after `'get_county'`; `list_filter = [CountyFilter, 'air_district', EmissionsYearFilter, SourceTypeFilter]`.
- `readonly_fields` gains `'air_district'` after `'county_code'`; the first fieldset's fields become `['sqid', ('county_code', 'air_district', 'facid'), 'name', 'sic_code', 'metadata_year']`.

- [ ] **Step 11: Move the API**

Create `camp/api/v2/emissions/` from `git show HEAD:camp/api/v2/ceidars/<file>` for `__init__.py`, `endpoints.py`, `filters.py`, `serializers.py`, `urls.py`, with these changes only:
- every `camp.apps.ceidars.models` import → `camp.apps.emissions.models`; docstrings say "CEIDARS" → "facility emissions".
- `urls.py`: `app_name = 'emissions'`.
- `serializers.py`: `EmissionsSerializer.fields` uses `'pm'` in place of `'pm25'`; `FacilitySerializer.fields` gains, after `'facid'`:
  ```python
  ('air_district_id', lambda f: f.air_district.sqid),
  ('air_district', lambda f: f.air_district.name),
  ```

Then `git rm -rq camp/api/v2/ceidars` and in `camp/api/v2/urls.py` replace the `ceidars/` line with:

```python
    path('emissions/', include('camp.api.v2.emissions.urls', namespace='emissions')),
```

Create `camp/api/v2/emissions/tests.py`:

```python
from django.contrib.gis.geos import Point
from django.test import TestCase
from django.urls import reverse

from camp.apps.emissions.models import EmissionsRecord, Facility


class FacilityListTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def names(self, **params):
        response = self.client.get(reverse('api:v2:emissions:list'), params)
        assert response.status_code == 200
        return [row['name'] for row in response.json()['data']]

    def test_defaults_to_the_latest_year(self):
        response = self.client.get(reverse('api:v2:emissions:list'))
        data = response.json()['data']
        assert {row['name'] for row in data} == {'TEST PLANT', 'TEST GAS STATION', 'TEST CEMENT'}
        assert {row['emissions']['year'] for row in data} == {2024}

    def test_specific_year(self):
        assert set(self.names(year=2023)) == {'TEST PLANT', 'TEST GAS STATION'}

    def test_invalid_year_returns_empty_list(self):
        assert self.names(year='garbage') == []

    def test_sources(self):
        assert set(self.names(sources='major')) == {'TEST PLANT', 'TEST CEMENT'}
        assert self.names(sources='minor') == ['TEST GAS STATION']

    def test_region_filters(self):
        assert self.names(county='fresno') == ['TEST PLANT']
        assert self.names(city='fresno') == ['TEST PLANT']
        assert self.names(zipcode='93728') == ['TEST PLANT']

    def test_carries_district_and_total_pm(self):
        response = self.client.get(reverse('api:v2:emissions:list'), {'county': 'fresno'})
        row = response.json()['data'][0]
        assert row['air_district'] == 'San Joaquin Valley APCD'
        assert row['emissions']['pm'] is not None
        assert 'pm25' not in row['emissions']

    def test_excludes_facilities_without_a_point(self):
        Facility.objects.filter(name='TEST PLANT').update(point=None)
        assert 'TEST PLANT' not in self.names()


class YearListTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def test_distinct_years_descending(self):
        response = self.client.get(reverse('api:v2:emissions:years'))
        assert response.json()['data'] == [2024, 2023]

    def test_empty(self):
        EmissionsRecord.objects.all().delete()
        response = self.client.get(reverse('api:v2:emissions:years'))
        assert response.json()['data'] == []


class FacilityDetailTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def test_full_history_newest_first(self):
        facility = Facility.objects.get(name='TEST PLANT')
        response = self.client.get(reverse('api:v2:emissions:detail', kwargs={'facility_id': facility.sqid}))
        data = response.json()['data']
        assert data['name'] == 'TEST PLANT'
        assert [row['year'] for row in data['emissions']] == [2024, 2023]

    def test_unknown_sqid_is_404(self):
        response = self.client.get(reverse('api:v2:emissions:detail', kwargs={'facility_id': 'doesnotexist'}))
        assert response.status_code == 404
```

- [ ] **Step 12: Point CLAUDE.md at the new model**

In `CLAUDE.md` (Key Conventions, sqids bullet) change ``following the pattern in `camp/apps/ceidars/models.py` `` to ``following the pattern in `camp/apps/emissions/models.py` ``.

- [ ] **Step 13: Run everything touched**

Run: `$TEST camp/apps/emissions camp/api/v2/emissions camp/apps/regions`
Expected: all PASS. Then `grep -rn "apps.ceidars\|api.v2.ceidars\|ceidars.yaml" camp fixtures` prints only `camp/settings/base.py` (the still-installed shell) and `camp/apps/ceidars/`.

- [ ] **Step 14: Commit**

```bash
git add camp/apps/emissions camp/api/v2/emissions fixtures/emissions.yaml \
  camp/apps/ceidars/models.py camp/apps/ceidars/migrations/0002_delete_models.py \
  camp/settings/base.py camp/api/v2/urls.py CLAUDE.md
git add -u camp/apps/ceidars camp/api/v2/ceidars fixtures/ceidars.yaml
git commit -m "feat(emissions): move CEIDARS into an emissions app keyed by air district

Whole-county CEIDARS imports (Kern includes the Eastern Kern APCD), facilities
identified by (county, district, FACID), CARB's PMT stored as total PM, and
covered counties read from the county Regions. The ceidars app keeps only a
migration that drops its tables."
```

---
### Task 3: Sectors

**Files:**
- Modify: `camp/apps/emissions/models.py` (add `Facility.Sector` + `sector` field)
- Create: `camp/apps/emissions/migrations/0002_facility_sector.py` (generated)
- Create: `camp/apps/emissions/sectors.py`
- Create: `camp/apps/emissions/management/commands/assign_sectors.py`
- Modify: `camp/apps/emissions/management/commands/import_ceidars.py` (set sector)
- Modify: `camp/apps/emissions/admin.py` (sector in list_display/list_filter/readonly/fieldset)
- Modify: `camp/api/v2/emissions/serializers.py` (sector fields)
- Modify: `fixtures/emissions.yaml` (sector per facility)
- Commit: `datafiles/sic-codes.csv` (already present on the branch)
- Test: `camp/apps/emissions/tests/test_sectors.py`, one new test in `test_import_ceidars.py`

**Interfaces:**
- Consumes: `Facility`, `EmissionsRecord` (Task 2).
- Produces: `Facility.Sector` (TextChoices, values below), `Facility.sector` (CharField, default `'other'`); `sectors.sector_for_sic(sic: int|None) -> Facility.Sector`; `sectors.sector_description(sector) -> str`; `sectors.sic_title(sic: int|None) -> str|None`; `sectors.SECTORS` (ordered list of `(Sector, codes, description)`).

- [ ] **Step 1: Write the failing tests**

Create `camp/apps/emissions/tests/test_sectors.py`:

```python
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from camp.apps.emissions import sectors
from camp.apps.emissions.models import Facility

S = Facility.Sector


class SectorForSicTests(TestCase):
    def test_every_sector_but_other_has_codes_and_a_description(self):
        listed = [sector for sector, codes, description in sectors.SECTORS]
        assert set(listed) == set(S) - {S.OTHER}
        for sector, codes, description in sectors.SECTORS:
            assert codes
            assert description
        assert sectors.sector_description(S.OTHER)

    def test_specific_sectors_win_over_the_ranges_that_contain_them(self):
        expected = {
            3221: S.GLASS, 3211: S.GLASS,
            3241: S.CEMENT_MINERALS, 3273: S.CEMENT_MINERALS, 3296: S.CEMENT_MINERALS,
            2084: S.WINERIES_BEVERAGES,
            2034: S.FOOD_PROCESSING, 2048: S.FOOD_PROCESSING,
            2911: S.REFINING_FUELS, 2951: S.REFINING_FUELS, 4612: S.REFINING_FUELS, 5171: S.REFINING_FUELS,
            723: S.CROP_PROCESSING, 724: S.CROP_PROCESSING,
            241: S.DAIRIES_LIVESTOCK, 211: S.DAIRIES_LIVESTOCK,
            173: S.FARMS,
            1311: S.OIL_GAS, 1389: S.OIL_GAS,
            1474: S.MINING, 1442: S.MINING,
            2875: S.CHEMICALS,
            4911: S.POWER_PLANTS, 4931: S.POWER_PLANTS,
            4953: S.WASTE_WATER, 4941: S.WASTE_WATER, 9511: S.WASTE_WATER,
            4812: S.TELECOM,
            4225: S.TRANSPORTATION,
            5541: S.GAS_STATIONS, 7532: S.AUTO_REPAIR, 7538: S.AUTO_REPAIR, 7216: S.DRY_CLEANERS,
            2711: S.MANUFACTURING, 3479: S.MANUFACTURING,
            8062: S.HOSPITALS_SCHOOLS, 8211: S.HOSPITALS_SCHOOLS,
            9711: S.GOVERNMENT_MILITARY, 9199: S.GOVERNMENT_MILITARY,
            5812: S.COMMERCIAL, 5411: S.COMMERCIAL,
            1521: S.OTHER,
            None: S.OTHER,
        }
        for sic, sector in expected.items():
            assert sectors.sector_for_sic(sic) == sector, sic


class SicTitleTests(TestCase):
    def test_titles(self):
        assert sectors.sic_title(3221) == 'Glass Containers'
        assert sectors.sic_title(723) == 'Crop Preparation Services for Market, Except Cotton Ginning'
        assert sectors.sic_title(1) is None
        assert sectors.sic_title(None) is None


class AssignSectorsTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def test_fixes_only_mismatched_rows(self):
        Facility.objects.filter(name='TEST PLANT').update(sector=S.OTHER)
        out = StringIO()
        call_command('assign_sectors', stdout=out)
        assert Facility.objects.get(name='TEST PLANT').sector == S.GLASS
        assert Facility.objects.get(name='TEST CEMENT').sector == S.CEMENT_MINERALS
        assert '1 facilities updated' in out.getvalue()
```

Append to `ImportCeidarsTests` in `camp/apps/emissions/tests/test_import_ceidars.py`:

```python
    def test_sets_sector_from_sic(self):
        self.run_import(county='fresno')
        assert Facility.objects.get(county_code=10, facid=1).sector == Facility.Sector.POWER_PLANTS
```

Run: `$TEST camp/apps/emissions/tests/test_sectors.py`
Expected: ERROR (`cannot import name 'sectors'`).

- [ ] **Step 2: Add the choices and field**

In `camp/apps/emissions/models.py`, inside `class Facility` directly above `objects = FacilityManager()`:

```python
    # Plain-language industry groups over SIC codes; the SIC -> sector map is
    # camp/apps/emissions/sectors.py. Adding one: a choice here, its codes
    # there (migration is choices-only), then `assign_sectors`.
    class Sector(models.TextChoices):
        DAIRIES_LIVESTOCK = 'dairies-livestock', _('Dairies & livestock')
        FARMS = 'farms', _('Farms & orchards')
        CROP_PROCESSING = 'crop-processing', _('Crop processing & cotton gins')
        OIL_GAS = 'oil-gas', _('Oil & gas production')
        MINING = 'mining', _('Mining & quarries')
        GLASS = 'glass', _('Glass manufacturing')
        CEMENT_MINERALS = 'cement-minerals', _('Cement, concrete & minerals')
        REFINING_FUELS = 'refining-fuels', _('Refineries, fuel terminals & pipelines')
        WINERIES_BEVERAGES = 'wineries-beverages', _('Wineries & beverages')
        FOOD_PROCESSING = 'food-processing', _('Food processing')
        CHEMICALS = 'chemicals', _('Chemicals & fertilizers')
        POWER_PLANTS = 'power-plants', _('Power plants')
        WASTE_WATER = 'waste-water', _('Waste, water & recycling')
        TELECOM = 'telecom', _('Telecommunications')
        TRANSPORTATION = 'transportation', _('Transportation & warehousing')
        GAS_STATIONS = 'gas-stations', _('Gas stations')
        AUTO_REPAIR = 'auto-repair', _('Auto body & repair')
        DRY_CLEANERS = 'dry-cleaners', _('Dry cleaners')
        MANUFACTURING = 'manufacturing', _('Other manufacturing')
        HOSPITALS_SCHOOLS = 'hospitals-schools', _('Hospitals & schools')
        GOVERNMENT_MILITARY = 'government-military', _('Government & military')
        COMMERCIAL = 'commercial', _('Commercial & services')
        OTHER = 'other', _('Other')
```

and after `sic_code`:

```python
    sector = models.CharField(_('Sector'), max_length=32, choices=Sector.choices, default=Sector.OTHER, db_index=True)
```

Generate: `... test python manage.py makemigrations emissions --name facility_sector`.

- [ ] **Step 3: Write `sectors.py`**

Create `camp/apps/emissions/sectors.py`:

```python
"""
SIC code -> Facility.Sector, and SIC titles.

SECTORS is walked in order and the first match wins, so a specific sector
(glass, cement, refining, wineries) sits ahead of the broad range that
contains it (manufacturing, food processing). SIC codes are ints (0723 is
723); a tuple is an inclusive (low, high) range. Built from the 2024 SIC
distribution across the covered counties.
"""

import csv
import io
from functools import lru_cache

from camp.apps.emissions.models import Facility
from camp.utils.datafiles import datafile

S = Facility.Sector

SECTORS = [
    (S.DAIRIES_LIVESTOCK, [(200, 299)],
     'Dairies, cattle feedlots, poultry and other animal operations.'),
    (S.FARMS, [(100, 199)],
     'Crop farms and orchards with permitted equipment, such as irrigation pump engines.'),
    (S.CROP_PROCESSING, [(700, 799)],
     'Cotton gins, nut hullers and other operations that prepare crops for market.'),
    (S.OIL_GAS, [(1300, 1399)],
     'Oil and natural gas fields and the services that support them.'),
    (S.MINING, [(1000, 1299), (1400, 1499)],
     'Quarries, sand and gravel pits, and mineral mines.'),
    (S.GLASS, [3211, 3221, 3229, 3231],
     'Plants that make flat glass, bottles and jars, and other glass products.'),
    (S.CEMENT_MINERALS, [(3240, 3299)],
     'Cement kilns, concrete plants and other stone, clay and mineral products.'),
    (S.REFINING_FUELS, [2911, (2950, 2999), (4610, 4619), (4922, 4925), 5171, 5172],
     'Petroleum refineries, asphalt plants, fuel terminals and pipelines.'),
    (S.WINERIES_BEVERAGES, [(2080, 2087)],
     'Wineries, breweries, distilleries and soft drink plants.'),
    (S.FOOD_PROCESSING, [(2000, 2099)],
     'Canneries, dairy processors, fruit and nut processing, and animal feed mills.'),
    (S.CHEMICALS, [(2800, 2899)],
     'Chemical plants and fertilizer and compost operations.'),
    (S.POWER_PLANTS, [4911, 4931, 4939, 4961],
     'Power plants and cogeneration facilities that make electricity or steam.'),
    (S.WASTE_WATER, [(4940, 4959), 4971, 5093, 9511],
     'Landfills, sewage treatment, water systems and recycling yards.'),
    (S.TELECOM, [(4800, 4899)],
     'Phone, cell and broadcast sites, mostly for their backup generators.'),
    (S.TRANSPORTATION, [(4000, 4799)],
     'Railroads, trucking, airports and warehouses.'),
    (S.GAS_STATIONS, [5541],
     'Gasoline stations.'),
    (S.AUTO_REPAIR, [7532, 7538],
     'Auto body, paint and repair shops.'),
    (S.DRY_CLEANERS, [7216],
     'Dry cleaners.'),
    (S.MANUFACTURING, [(2100, 2799), (3000, 3999)],
     'Other manufacturing: metal, plastics, wood, paper, printing and more.'),
    (S.HOSPITALS_SCHOOLS, [(8000, 8099), (8200, 8299)],
     'Hospitals, clinics, schools, colleges and universities.'),
    (S.GOVERNMENT_MILITARY, [(9100, 9999)],
     'Government facilities, prisons, fire stations and military bases.'),
    (S.COMMERCIAL, [(5000, 5999), (6000, 6999), (7000, 7999), (8100, 8199), (8300, 8999)],
     'Stores, restaurants, offices and other businesses.'),
]

OTHER_DESCRIPTION = "Facilities whose industry code doesn't fit another sector."

_DESCRIPTIONS = {sector: description for sector, _codes, description in SECTORS}


def _matches(sic, codes):
    for code in codes:
        if isinstance(code, tuple):
            if code[0] <= sic <= code[1]:
                return True
        elif sic == code:
            return True
    return False


def sector_for_sic(sic):
    if sic is None:
        return S.OTHER
    for sector, codes, _description in SECTORS:
        if _matches(sic, codes):
            return sector
    return S.OTHER


def sector_description(sector):
    return _DESCRIPTIONS.get(sector, OTHER_DESCRIPTION)


@lru_cache(maxsize=1)
def _sic_titles():
    text = datafile('sic-codes.csv')
    lines = [line for line in text.splitlines() if not line.startswith('#')]
    return {int(row['SIC']): row['Description'] for row in csv.DictReader(io.StringIO('\n'.join(lines)))}


def sic_title(sic):
    if sic is None:
        return None
    return _sic_titles().get(int(sic))
```

- [ ] **Step 4: Write `assign_sectors` and hook the importer**

Create `camp/apps/emissions/management/commands/assign_sectors.py`:

```python
from django.core.management.base import BaseCommand

from camp.apps.emissions.models import Facility
from camp.apps.emissions.sectors import sector_for_sic


class Command(BaseCommand):
    help = "Re-apply sectors.py's SIC -> sector map to every facility (run after editing sectors.py)."

    def handle(self, *args, **options):
        changed = []
        for facility in Facility.objects.only('id', 'sic_code', 'sector').iterator():
            sector = sector_for_sic(facility.sic_code)
            if facility.sector != sector:
                facility.sector = sector
                changed.append(facility)
        Facility.objects.bulk_update(changed, ['sector'], batch_size=1000)
        self.stdout.write(f'{len(changed)} facilities updated.')
```

In `import_ceidars.py`: add `from camp.apps.emissions.sectors import sector_for_sic`; add `'sector': sector_for_sic(sic_code),` to the `get_or_create` defaults; and inside the `metadata_year` update block add `facility.sector = sector_for_sic(sic_code)` after `facility.sic_code = sic_code`.

- [ ] **Step 5: Surface sector in admin, API and fixture**

- `admin.py`: `list_display` gains `'sector'` after `'sic_code'`; `list_filter` gains `'sector'` after `'air_district'`; `readonly_fields` gains `'sector'` after `'sic_code'`; the first fieldset's fields become `['sqid', ('county_code', 'air_district', 'facid'), 'name', ('sic_code', 'sector'), 'metadata_year']`.
- `camp/api/v2/emissions/serializers.py` `FacilitySerializer.fields`, after `'sic_code'`:
  ```python
  'sector',
  ('sector_label', lambda f: f.get_sector_display()),
  ```
- `fixtures/emissions.yaml`: add `sector: glass` to facility 1, `sector: gas-stations` to facility 2, `sector: cement-minerals` to facility 3 (after each `sic_code`).

- [ ] **Step 6: Run the tests**

Run: `$TEST camp/apps/emissions camp/api/v2/emissions`
Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add camp/apps/emissions/models.py camp/apps/emissions/migrations/0002_facility_sector.py \
  camp/apps/emissions/sectors.py camp/apps/emissions/management/commands/assign_sectors.py \
  camp/apps/emissions/management/commands/import_ceidars.py camp/apps/emissions/admin.py \
  camp/api/v2/emissions/serializers.py fixtures/emissions.yaml datafiles/sic-codes.csv \
  camp/apps/emissions/tests/test_sectors.py camp/apps/emissions/tests/test_import_ceidars.py
git commit -m "feat(emissions): group facilities into plain-language sectors by SIC code"
```

---

### Task 4: CARB county inventory (CEPAM)

**Files:**
- Modify: `camp/apps/emissions/models.py` (add `CountyInventory`)
- Create: `camp/apps/emissions/migrations/0003_countyinventory.py` (generated)
- Create: `camp/apps/emissions/cepam.py`
- Create: `camp/apps/emissions/management/commands/import_cepam.py`
- Modify: `camp/apps/emissions/admin.py` (register `CountyInventory`, read-only)
- Test: `camp/apps/emissions/tests/test_cepam.py`

**Interfaces:**
- Consumes: `carb.carb_counties`, `carb.parse_years` (Task 2).
- Produces: `CountyInventory` (fields below; `SourceType` choices `stationary|areawide|mobile|natural`); `cepam.INVENTORY = '2019V104ADJ'`; `cepam.BASE_YEAR = 2017`; `cepam.POLLUTANT_FIELDS = ('tog', 'rog', 'co', 'nox', 'sox', 'pm', 'pm10', 'pm25')`; `cepam.fetch_text(year, county_code) -> str`; `cepam.parse(text, county, year) -> list[CountyInventory]`.

- [ ] **Step 1: Write the failing tests**

Create `camp/apps/emissions/tests/test_cepam.py`:

```python
from unittest.mock import MagicMock, patch

import pytest

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from camp.apps.emissions import cepam
from camp.apps.emissions.models import CountyInventory
from camp.apps.regions.models import Region

HEADER = '"DATA_SOURCE","YEAR","AREA","SEASON","EMISSION_TYPE","SRC_TYPE","EIC","EICSUMN","EICSOUN","EICMATN","EICSUBN","TOG","ROG","COT","NOX","SOX","PM","PM10","PM2_5"\n'
ROWS = (
    '"2019V104ADJ",2017,"FRESNO","Annual Average","Grown and Controlled","STATIONARY"," 010-005-0110-0000","ELECTRIC UTILITIES","BOILERS","NATURAL GAS","SUB-CATEGORY UNSPECIFIED",.1,.2,.3,.4,.5,.6,.7,.8\n'
    '"2019V104ADJ",2017,"FRESNO","Annual Average","Grown and Controlled","AREAWIDE"," 620-614-5400-0000","FARMING OPERATIONS","LIVESTOCK WASTE","DAIRY CATTLE","SUB-CATEGORY UNSPECIFIED",1,2,,,,.5,.4,.1\n'
    '"2019V104ADJ",2017,"FRESNO","Annual Average","Grown and Controlled","MOBILE"," 723-723-1110-0000","HEAVY HEAVY DUTY DIESEL TRUCKS (HHDDT)","HHDDT","DIESEL","SUB-CATEGORY UNSPECIFIED",.3,.3,1,10,.01,.2,.2,.19\n'
    '"2019V104ADJ",2017,"FRESNO","Annual Average","Grown and Controlled","NATURAL+UNPLANNED FIRE EVENT"," 910-910-0000-0000","WILDFIRES","WILDFIRES","ALL VEGETATION","SUB-CATEGORY UNSPECIFIED",5,4,3,2,1,1,1,1\n'
    ',,,,,,,,,,,,,,,,,,\n'
    '\n\n'
)
CSV = HEADER + ROWS


class ParseTests(TestCase):
    fixtures = ['regions.yaml']

    def test_parses_rows_and_skips_blank_eics(self):
        county = Region.objects.get(type=Region.Type.COUNTY, slug='fresno')
        rows = cepam.parse(CSV, county, 2017)
        assert len(rows) == 4
        stationary = rows[0]
        assert stationary.county == county
        assert stationary.year == 2017
        assert stationary.inventory == '2019V104ADJ'
        assert stationary.source_type == CountyInventory.SourceType.STATIONARY
        assert stationary.eic == '010-005-0110-0000'
        assert stationary.summary_name == 'ELECTRIC UTILITIES'
        assert stationary.nox == 0.4
        assert stationary.pm25 == 0.8
        assert [row.source_type for row in rows] == ['stationary', 'areawide', 'mobile', 'natural']
        assert rows[1].nox is None

    def test_unknown_source_type_is_an_error(self):
        county = Region.objects.get(type=Region.Type.COUNTY, slug='fresno')
        bad = HEADER + ROWS.splitlines()[0].replace('"STATIONARY"', '"ORBITAL"') + '\n'
        with pytest.raises(ValueError, match='ORBITAL'):
            cepam.parse(bad, county, 2017)


class ImportCepamTests(TestCase):
    fixtures = ['regions.yaml']

    def setUp(self):
        self.fresno = Region.objects.get(type=Region.Type.COUNTY, slug='fresno')
        self.fresno.metadata['ca_county_code'] = '10'
        self.fresno.save(update_fields=['metadata'])

    def run_import(self, text=CSV, year='2017', urls=None):
        def get(url, params=None, **kwargs):
            if urls is not None:
                urls.append(params)
            mock = MagicMock()
            mock.text = text
            mock.raise_for_status.return_value = None
            return mock
        with patch('camp.apps.emissions.cepam.requests.get', side_effect=get):
            call_command('import_cepam', year=year, county='fresno')

    def test_imports_and_replaces_idempotently(self):
        self.run_import()
        self.run_import()
        assert CountyInventory.objects.filter(county=self.fresno, year=2017).count() == 4

    def test_requests_whole_county_by_carb_number(self):
        params = []
        self.run_import(urls=params)
        assert params[0]['F_CO'] == 10
        assert params[0]['F_YR'] == 2017
        assert params[0]['F_AREA'] == 'CO'
        assert params[0]['SP'] == cepam.INVENTORY

    def test_year_range(self):
        self.run_import(year='2016-2017')
        assert set(CountyInventory.objects.values_list('year', flat=True)) == {2016, 2017}

    def test_empty_response_keeps_existing_rows(self):
        self.run_import()
        self.run_import(text=HEADER)
        assert CountyInventory.objects.count() == 4

    def test_bad_year_range_is_an_error(self):
        with pytest.raises(CommandError):
            self.run_import(year='2024-2010')
```

Run: `$TEST camp/apps/emissions/tests/test_cepam.py`
Expected: ERROR (`cannot import name 'cepam'`).

- [ ] **Step 2: Add the model**

Append to `camp/apps/emissions/models.py`:

```python
class CountyInventory(models.Model):
    """
    One county's CARB emission inventory (CEPAM) for one emission inventory
    code (EIC) and year: every source, not only permitted facilities, in
    tons/day (annual average) as CARB publishes it. Only the inventory's base
    year is an inventory; other years are CARB's back-casts and projections.
    """

    class SourceType(models.TextChoices):
        STATIONARY = 'stationary', _('Stationary')
        AREAWIDE = 'areawide', _('Areawide')
        MOBILE = 'mobile', _('Mobile')
        NATURAL = 'natural', _('Natural')

    county = models.ForeignKey('regions.Region', verbose_name=_('County'), on_delete=models.CASCADE, related_name='+')
    year = models.IntegerField(_('Year'))
    inventory = models.CharField(_('Inventory'), max_length=32)
    source_type = models.CharField(_('Source type'), max_length=16, choices=SourceType.choices, db_index=True)
    eic = models.CharField(_('EIC'), max_length=20)
    summary_name = models.CharField(_('Summary category'), max_length=128, blank=True)
    source_name = models.CharField(_('Source'), max_length=128, blank=True)
    material_name = models.CharField(_('Material'), max_length=128, blank=True)
    subcategory_name = models.CharField(_('Subcategory'), max_length=128, blank=True)

    tog = models.FloatField(_('TOG (tons/day)'), null=True)
    rog = models.FloatField(_('ROG (tons/day)'), null=True)
    co = models.FloatField(_('CO (tons/day)'), null=True)
    nox = models.FloatField(_('NOx (tons/day)'), null=True)
    sox = models.FloatField(_('SOx (tons/day)'), null=True)
    pm = models.FloatField(_('Total PM (tons/day)'), null=True)
    pm10 = models.FloatField(_('PM10 (tons/day)'), null=True)
    pm25 = models.FloatField(_('PM2.5 (tons/day)'), null=True)

    class Meta:
        unique_together = [('county', 'year', 'inventory', 'eic')]
        verbose_name_plural = 'county inventories'

    def __str__(self):
        return f'{self.eic} {self.county} {self.year}'
```

Generate: `... test python manage.py makemigrations emissions --name countyinventory`.

- [ ] **Step 3: Write `cepam.py`**

Create `camp/apps/emissions/cepam.py`:

```python
"""
CARB's county emission inventory (CEPAM) by emission inventory code (EIC).

Whole-county requests only: the form that splits a county by air district
sits behind bot protection, and the facility inventory is whole-county too.
"""

import csv
import io
import time

import requests

from camp.apps.emissions.models import CountyInventory

# The 2019 SIP inventory: base year 2017, every other year back-cast or
# projected ("grown and controlled"). Change here when CARB publishes a
# newer inventory.
INVENTORY = '2019V104ADJ'
BASE_YEAR = 2017

CSV_URL = 'https://www.arb.ca.gov/app/emsinv/iframe/2021/emsbyeic.csv'

SOURCE_TYPES = {
    'STATIONARY': CountyInventory.SourceType.STATIONARY,
    'AREAWIDE': CountyInventory.SourceType.AREAWIDE,
    'MOBILE': CountyInventory.SourceType.MOBILE,
    'NATURAL+UNPLANNED FIRE EVENT': CountyInventory.SourceType.NATURAL,
}

# CSV column -> CountyInventory field (tons/day)
POLLUTANT_COLUMNS = {
    'TOG': 'tog', 'ROG': 'rog', 'COT': 'co', 'NOX': 'nox', 'SOX': 'sox',
    'PM': 'pm', 'PM10': 'pm10', 'PM2_5': 'pm25',
}
POLLUTANT_FIELDS = tuple(POLLUTANT_COLUMNS.values())


def params(year, county_code):
    return {
        'F_YR': year, 'F_DIV': 0, 'F_SEASON': 'A',
        'SP': INVENTORY, 'SPN': INVENTORY,
        'F_AREA': 'CO', 'F_COAB': '', 'F_CO': county_code,
    }


def fetch_text(year, county_code, retries=5):
    for attempt in range(retries):
        try:
            response = requests.get(CSV_URL, params=params(year, county_code), timeout=60)
            response.raise_for_status()
            return response.text
        except requests.RequestException:
            if attempt == retries - 1:
                raise
            time.sleep((2 ** attempt) * 0.5)


def _float(value):
    value = (value or '').strip()
    return float(value) if value else None


def parse(text, county, year):
    """Unsaved CountyInventory rows; rows without an EIC (blank trailer lines) are skipped."""
    rows = []
    for row in csv.DictReader(io.StringIO(text)):
        eic = (row.get('EIC') or '').strip()
        if not eic:
            continue
        source = (row.get('SRC_TYPE') or '').strip()
        if source not in SOURCE_TYPES:
            raise ValueError(f'Unknown CEPAM source type {source!r} for EIC {eic}')
        rows.append(CountyInventory(
            county=county,
            year=year,
            inventory=INVENTORY,
            source_type=SOURCE_TYPES[source],
            eic=eic,
            summary_name=(row.get('EICSUMN') or '').strip(),
            source_name=(row.get('EICSOUN') or '').strip(),
            material_name=(row.get('EICMATN') or '').strip(),
            subcategory_name=(row.get('EICSUBN') or '').strip(),
            **{field: _float(row.get(column)) for column, field in POLLUTANT_COLUMNS.items()},
        ))
    return rows
```

- [ ] **Step 4: Write the command and admin**

Create `camp/apps/emissions/management/commands/import_cepam.py`:

```python
import requests

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from camp.apps.emissions import carb, cepam
from camp.apps.emissions.models import CountyInventory


class Command(BaseCommand):
    help = "Import CARB's county emission inventory (CEPAM) by EIC for the covered counties."

    def add_arguments(self, parser):
        parser.add_argument('--year', required=True, help='A year (2024) or an inclusive range (2010-2024)')
        parser.add_argument('--county', help='Limit to one covered county, by slug (e.g. fresno)')

    def handle(self, *args, **options):
        try:
            years = carb.parse_years(options['year'])
            counties = carb.carb_counties(options.get('county'))
        except (ValueError, carb.CountyConfigError) as exc:
            raise CommandError(str(exc))

        failed = []
        for year in years:
            for county_code, county in counties:
                label = f'{county.name} {year}'
                try:
                    rows = cepam.parse(cepam.fetch_text(year, county_code), county, year)
                except (requests.RequestException, ValueError) as exc:
                    self.stderr.write(f'{label}: {exc}')
                    failed.append(label)
                    continue
                if not rows:
                    self.stderr.write(f'{label}: no rows returned; existing rows kept.')
                    continue
                with transaction.atomic():
                    CountyInventory.objects.filter(county=county, year=year, inventory=cepam.INVENTORY).delete()
                    CountyInventory.objects.bulk_create(rows, batch_size=1000)
                self.stdout.write(f'{label}: {len(rows)} EIC rows')

        if failed:
            raise CommandError(f'Import incomplete for: {", ".join(failed)}')
```

In `admin.py` register it read-only:

```python
@admin.register(CountyInventory)
class CountyInventoryAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ['eic', 'county', 'year', 'source_type', 'summary_name', 'source_name', 'nox', 'pm10']
    list_filter = ['year', 'source_type', 'county']
    search_fields = ['eic', 'summary_name', 'source_name', 'material_name']
```

(and add `CountyInventory` to the `.models` import).

- [ ] **Step 5: Run the tests**

Run: `$TEST camp/apps/emissions`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add camp/apps/emissions/models.py camp/apps/emissions/migrations/0003_countyinventory.py \
  camp/apps/emissions/cepam.py camp/apps/emissions/management/commands/import_cepam.py \
  camp/apps/emissions/admin.py camp/apps/emissions/tests/test_cepam.py
git commit -m "feat(emissions): import CARB's county emission inventory (CEPAM) by EIC"
```

---
### Task 5: Pollutants and the stats layer

**Files:**
- Create: `camp/apps/emissions/pollutants.py`
- Create: `camp/apps/emissions/stats.py`
- Test: `camp/apps/emissions/tests/test_stats.py`

**Interfaces:**
- Consumes: `EmissionsRecord`, `Facility` (+ `Sector`), `MINOR_SOURCE_SIC_CODES`, `CountyInventory`, `cepam.INVENTORY`, `cepam.BASE_YEAR`.
- Produces (`pollutants.py`): `Pollutant(key, label, name, toxic=False)` with `.unit` (`'tons'`/`'lbs'`), `.factor` (1/2000), `.display(tons) -> float|None`; `CRITERIA`, `TOXICS` (lists, display order), `POLLUTANTS` (dict by key), `DEFAULT_CRITERIA = 'nox'`, `DEFAULT_TOXIC = 'benzene'`, `get_pollutant(key, toxic=False) -> Pollutant`.
- Produces (`stats.py`):
  - `Scope(year, county, pollutant, minor=False)` (frozen dataclass) with `.toxics`, `.key(name, *extra) -> str`, `.params(**overrides) -> dict`, `.query(**overrides) -> str` (`''` or `'?a=b'`).
  - `available_years() -> list[int]` ascending; `latest_year() -> int|None`; `resolve_scope(params) -> Scope`.
  - `records(scope, *, all_years=False) -> QuerySet[EmissionsRecord]`.
  - `totals(scope) -> dict` (`'facilities'` + every pollutant key, tons, floats or None).
  - `ranks(scope) -> dict[facility_id, int]` (competition ranking, positive values only).
  - `with_ranks(records, ranks) -> list[tuple[int|None, EmissionsRecord]]`.
  - `facility_table(scope, *, sector=None, district=None, city=None, q=None, sort='-value') -> QuerySet[EmissionsRecord]` (annotated `value`).
  - `sector_breakdown(scope) -> list[dict(sector, label, facilities, value, share)]`.
  - `county_breakdown(scope, *, sector=None) -> list[dict(county, facilities, value, share)]` (always every covered county).
  - `by_year(scope, *, facility=None, sector=None) -> list[dict(year, value)]` (tons).
  - `sector_trends(scope) -> dict[sector_value, list[dict(year, value)]]`.
  - `county_context(scope) -> dict|None` (`parts`, `total`, `facilities`, `facility_share`, `base_year`, `inventory`, `counties`), all tons/yr.
  - `facility_ranks(facility, year) -> list[dict(pollutant, value, county_rank, county_count, sector_rank, sector_count, county_share)]` (criteria only).
  - `facility_toxics(facility, year) -> list[dict(pollutant, value, previous, previous_year)]` (lbs/yr).
  - `large_changes(facility) -> list[dict(pollutant, year, previous_year, pct)]`.
  - `SORTS = ('-value', 'value', 'name', '-name', 'county', '-county')`.

All values are **tons** except where noted; templates convert with `pollutant.display()`.

- [ ] **Step 1: Write the failing tests**

Create `camp/apps/emissions/tests/test_stats.py`:

```python
from django.core.cache import cache
from django.http import QueryDict
from django.test import TestCase

from camp.apps.emissions import cepam, stats
from camp.apps.emissions.models import CountyInventory, EmissionsRecord, Facility
from camp.apps.emissions.pollutants import POLLUTANTS, get_pollutant
from camp.apps.regions.models import Region


def scope(**params):
    """A resolved Scope from query parameters, as a request would give them (strings)."""
    query = QueryDict(mutable=True)
    for key, value in params.items():
        query[key] = str(value)
    return stats.resolve_scope(query)


class StatsTestCase(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        cache.clear()
        self.fresno = Region.objects.get(type=Region.Type.COUNTY, slug='fresno')
        self.kern = Region.objects.get(type=Region.Type.COUNTY, slug='kern')
        self.plant = Facility.objects.get(name='TEST PLANT')
        self.cement = Facility.objects.get(name='TEST CEMENT')
        self.gas = Facility.objects.get(name='TEST GAS STATION')


class PollutantTests(TestCase):
    def test_units(self):
        assert POLLUTANTS['nox'].unit == 'tons'
        assert POLLUTANTS['nox'].display(2) == 2
        assert POLLUTANTS['benzene'].unit == 'lbs'
        assert POLLUTANTS['benzene'].display(0.001) == 2
        assert POLLUTANTS['pm'].label == 'Total PM'
        assert 'pm25' not in POLLUTANTS

    def test_get_pollutant_falls_back_to_the_kind_default(self):
        assert get_pollutant('rog').key == 'rog'
        assert get_pollutant('bogus').key == 'nox'
        assert get_pollutant('nox', toxic=True).key == 'benzene'
        assert get_pollutant('formaldehyde', toxic=True).key == 'formaldehyde'


class ScopeTests(StatsTestCase):
    def test_defaults(self):
        s = scope()
        assert s.year == 2024
        assert s.county is None
        assert s.pollutant.key == 'nox'
        assert not s.minor and not s.toxics

    def test_bad_values_fall_back(self):
        s = scope(year=1999, county='nowhere', pollutant='bogus')
        assert (s.year, s.county, s.pollutant.key) == (2024, None, 'nox')

    def test_toxics_and_county(self):
        s = scope(toxics=1, county='fresno', minor=1)
        assert s.toxics and s.minor
        assert s.pollutant.key == 'benzene'
        assert s.county == self.fresno

    def test_query_drops_defaults(self):
        assert scope().query() == ''
        assert scope(year=2023, county='fresno').query() == '?year=2023&county=fresno'
        assert scope().query(pollutant='rog') == '?pollutant=rog'
        assert scope(toxics=1).query() == '?toxics=1'


class TotalsAndRanksTests(StatsTestCase):
    def test_totals_exclude_minor_sources_by_default(self):
        totals = stats.totals(scope())
        assert totals['facilities'] == 2
        assert totals['nox'] == 106.0
        assert totals['rog'] is None
        assert stats.totals(scope(minor=1))['facilities'] == 3
        assert stats.totals(scope(minor=1))['rog'] == 0.2

    def test_county_scope(self):
        assert stats.totals(scope(county='kern'))['nox'] == 100.0

    def test_ranks(self):
        assert stats.ranks(scope()) == {self.cement.pk: 1, self.plant.pk: 2}

    def test_ties_share_a_rank(self):
        EmissionsRecord.objects.filter(facility=self.plant, year=2024).update(nox=100)
        assert stats.ranks(scope()) == {self.cement.pk: 1, self.plant.pk: 1}

    def test_facility_table_filters_and_sorts(self):
        names = [r.facility.name for r in stats.facility_table(scope())]
        assert names == ['TEST CEMENT', 'TEST PLANT']
        assert [r.facility.name for r in stats.facility_table(scope(), sort='name')] == ['TEST CEMENT', 'TEST PLANT']
        assert [r.facility.name for r in stats.facility_table(scope(), q='plant')] == ['TEST PLANT']
        assert [r.facility.name for r in stats.facility_table(scope(), sector='cement-minerals')] == ['TEST CEMENT']
        assert [r.facility.name for r in stats.facility_table(scope(), district='KER')] == ['TEST CEMENT']
        assert [r.facility.name for r in stats.facility_table(scope(), city='fresno')] == ['TEST PLANT']

    def test_with_ranks(self):
        s = scope()
        rows = stats.with_ranks(stats.facility_table(s), stats.ranks(s))
        assert [(rank, record.facility.name) for rank, record in rows] == [(1, 'TEST CEMENT'), (2, 'TEST PLANT')]


class BreakdownTests(StatsTestCase):
    def test_sector_breakdown(self):
        rows = stats.sector_breakdown(scope())
        assert rows[0]['sector'] == Facility.Sector.CEMENT_MINERALS
        assert rows[0]['value'] == 100.0
        assert round(rows[0]['share'], 3) == round(100 / 106, 3)
        assert rows[0]['facilities'] == 1

    def test_county_breakdown_ignores_the_county_scope(self):
        rows = stats.county_breakdown(scope(county='fresno'))
        assert {row['county'] for row in rows} == {self.fresno, self.kern}

    def test_county_breakdown_for_a_sector(self):
        rows = stats.county_breakdown(scope(), sector='glass')
        assert [(row['county'], row['value']) for row in rows] == [(self.fresno, 6.0)]

    def test_by_year(self):
        assert stats.by_year(scope()) == [{'year': 2023, 'value': 3.0}, {'year': 2024, 'value': 106.0}]
        assert stats.by_year(scope(), facility=self.plant) == [{'year': 2023, 'value': 3.0}, {'year': 2024, 'value': 6.0}]
        assert stats.by_year(scope(), sector='cement-minerals') == [{'year': 2024, 'value': 100.0}]

    def test_sector_trends(self):
        trends = stats.sector_trends(scope())
        assert trends['glass'] == [{'year': 2023, 'value': 3.0}, {'year': 2024, 'value': 6.0}]


class CountyContextTests(StatsTestCase):
    def inventory(self, county, source_type, nox):
        CountyInventory.objects.create(
            county=county, year=2024, inventory=cepam.INVENTORY, source_type=source_type,
            eic=f'{county.pk}-{source_type}', nox=nox,
        )

    def test_context_in_tons_per_year(self):
        self.inventory(self.fresno, 'stationary', 0.1)
        self.inventory(self.fresno, 'mobile', 0.9)
        self.inventory(self.kern, 'stationary', 1.0)
        context = stats.county_context(scope())
        assert round(context['total'], 6) == 2.0 * 365
        parts = {part['source_type']: part for part in context['parts']}
        assert round(parts['stationary']['tons'], 6) == 1.1 * 365
        assert round(parts['mobile']['share'], 6) == round(0.9 / 2.0, 6)
        assert parts['areawide']['tons'] == 0
        assert context['facilities'] == 106.0
        assert context['base_year'] == cepam.BASE_YEAR

    def test_county_scope_uses_that_county_only(self):
        self.inventory(self.fresno, 'stationary', 0.1)
        self.inventory(self.kern, 'stationary', 1.0)
        assert round(stats.county_context(scope(county='kern'))['total'], 6) == 365.0

    def test_none_for_toxics_or_missing_years(self):
        self.inventory(self.fresno, 'stationary', 0.1)
        assert stats.county_context(scope(toxics=1)) is None
        assert stats.county_context(scope(year=2023)) is None


class FacilityDetailStatsTests(StatsTestCase):
    def test_facility_ranks(self):
        rows = {row['pollutant'].key: row for row in stats.facility_ranks(self.cement, 2024)}
        assert rows['nox']['value'] == 100.0
        assert (rows['nox']['county_rank'], rows['nox']['county_count']) == (1, 1)
        assert (rows['nox']['sector_rank'], rows['nox']['sector_count']) == (1, 1)
        assert rows['nox']['county_share'] == 1.0
        assert rows['rog']['value'] is None

    def test_facility_toxics_in_lbs(self):
        rows = stats.facility_toxics(self.plant, 2024)
        assert [(row['pollutant'].key, row['value']) for row in rows] == [('benzene', 2.0)]
        assert rows[0]['previous'] is None

    def test_large_changes(self):
        # nox 3 -> 6 is +100%; pm 0.8 -> 1.0 (+25%) and pm10 0.5 -> 0.6 (+20%) are under the 50% threshold.
        changes = stats.large_changes(self.plant)
        assert [(c['pollutant'].key, c['year'], c['previous_year'], round(c['pct'])) for c in changes] == [('nox', 2024, 2023, 100)]
```

Run: `$TEST camp/apps/emissions/tests/test_stats.py`
Expected: ERROR (`cannot import name 'stats'`).

- [ ] **Step 2: Write `pollutants.py`**

```python
"""The pollutants the explorer can show, in display order."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Pollutant:
    key: str      # EmissionsRecord (and, for criteria, CountyInventory) field name
    label: str    # short, for pickers and column headers
    name: str     # spelled out
    toxic: bool = False

    @property
    def unit(self):
        # Toxic air contaminants are fractions of a ton; pounds read better.
        return 'lbs' if self.toxic else 'tons'

    @property
    def factor(self):
        return 2000 if self.toxic else 1

    def display(self, tons):
        return None if tons is None else float(tons) * self.factor


CRITERIA = [
    Pollutant('nox', 'NOx', 'Nitrogen oxides'),
    Pollutant('rog', 'ROG', 'Reactive organic gases'),
    Pollutant('pm', 'Total PM', 'Total particulate matter'),
    Pollutant('pm10', 'PM10', 'Particulate matter under 10 microns'),
    Pollutant('sox', 'SOx', 'Sulfur oxides'),
    Pollutant('co', 'CO', 'Carbon monoxide'),
    Pollutant('tog', 'TOG', 'Total organic gases'),
]

TOXICS = [
    Pollutant('benzene', 'Benzene', 'Benzene', toxic=True),
    Pollutant('formaldehyde', 'Formaldehyde', 'Formaldehyde', toxic=True),
    Pollutant('acetaldehyde', 'Acetaldehyde', 'Acetaldehyde', toxic=True),
    Pollutant('butadiene', '1,3-Butadiene', '1,3-Butadiene', toxic=True),
    Pollutant('chromium_hexavalent', 'Hexavalent chromium', 'Hexavalent chromium', toxic=True),
    Pollutant('naphthalene', 'Naphthalene', 'Naphthalene', toxic=True),
    Pollutant('perchloroethylene', 'Perchloroethylene', 'Perchloroethylene (dry cleaning solvent)', toxic=True),
    Pollutant('methylene_chloride', 'Methylene chloride', 'Methylene chloride', toxic=True),
    Pollutant('carbon_tetrachloride', 'Carbon tetrachloride', 'Carbon tetrachloride', toxic=True),
    Pollutant('dichlorobenzene', 'p-Dichlorobenzene', 'para-Dichlorobenzene', toxic=True),
]

POLLUTANTS = {pollutant.key: pollutant for pollutant in CRITERIA + TOXICS}
DEFAULT_CRITERIA = 'nox'
DEFAULT_TOXIC = 'benzene'


def get_pollutant(key, toxic=False):
    """The pollutant for `key` when it's of the requested kind, else that kind's default."""
    pollutant = POLLUTANTS.get(key)
    if pollutant is not None and pollutant.toxic == toxic:
        return pollutant
    return POLLUTANTS[DEFAULT_TOXIC if toxic else DEFAULT_CRITERIA]
```

- [ ] **Step 3: Write `stats.py`**

```python
"""
Aggregates for the Facility Emissions Explorer.

About 6,500 facilities x 15 years, so everything is computed per request from
EmissionsRecord and cached per scope for a day; no rollup tables. Values are
tons/yr (CEIDARS) unless a name says otherwise; templates convert toxics to
lbs with Pollutant.display().
"""

from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlencode

from django.core.cache import cache
from django.db.models import Count, F, Sum

from camp.apps.emissions import cepam
from camp.apps.emissions.models import MINOR_SOURCE_SIC_CODES, CountyInventory, EmissionsRecord, Facility
from camp.apps.emissions.pollutants import CRITERIA, DEFAULT_CRITERIA, DEFAULT_TOXIC, TOXICS, Pollutant, get_pollutant
from camp.apps.regions.models import Region

# Bump when the shape of anything cached here changes.
CACHE_VERSION = 1
CACHE_TIMEOUT = 60 * 60 * 24
# A year-over-year change larger than this gets the "may reflect estimation
# methods" note on a facility page.
LARGE_CHANGE = 0.5
SORTS = ('-value', 'value', 'name', '-name', 'county', '-county')
SORT_FIELDS = {'name': 'facility__name', 'county': 'facility__county__name'}


def _float(value):
    return None if value is None else float(value)


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def available_years():
    def compute():
        return sorted(EmissionsRecord.objects.values_list('year', flat=True).distinct())
    return cache.get_or_set(f'emissions:v{CACHE_VERSION}:years', compute, 60 * 60)


def latest_year():
    years = available_years()
    return years[-1] if years else None


@dataclass(frozen=True)
class Scope:
    year: Optional[int]
    county: Optional[Region]
    pollutant: Pollutant
    minor: bool = False

    @property
    def toxics(self):
        return self.pollutant.toxic

    def key(self, name, *extra):
        parts = [
            f'emissions:v{CACHE_VERSION}', name, self.year,
            self.county.pk if self.county else 'all',
            self.pollutant.key, int(self.minor), *extra,
        ]
        return ':'.join(str(part) for part in parts)

    def params(self, **overrides):
        """The scope as query parameters, leaving out every default."""
        values = {
            'year': self.year,
            'county': self.county.slug if self.county else None,
            'pollutant': self.pollutant.key,
            'toxics': '1' if self.toxics else None,
            'minor': '1' if self.minor else None,
        }
        values.update(overrides)
        if values.get('year') == latest_year():
            values['year'] = None
        default = DEFAULT_TOXIC if values.get('toxics') else DEFAULT_CRITERIA
        if values.get('pollutant') == default:
            values['pollutant'] = None
        return {key: value for key, value in values.items() if value not in (None, '')}

    def query(self, **overrides):
        params = self.params(**overrides)
        return f'?{urlencode(params)}' if params else ''


def resolve_scope(params):
    """Scope from a request's GET; anything unknown falls back to its default."""
    years = available_years()
    year = _int(params.get('year'))
    if year not in years:
        year = years[-1] if years else None
    county = None
    if params.get('county'):
        county = Region.objects.counties().filter(slug=params['county']).first()
    toxics = params.get('toxics') == '1'
    return Scope(
        year=year,
        county=county,
        pollutant=get_pollutant(params.get('pollutant'), toxic=toxics),
        minor=params.get('minor') == '1',
    )


def records(scope, *, all_years=False):
    queryset = EmissionsRecord.objects.all()
    if not all_years:
        queryset = queryset.filter(year=scope.year)
    if scope.county is not None:
        queryset = queryset.filter(facility__county=scope.county)
    if not scope.minor:
        queryset = queryset.exclude(facility__sic_code__in=MINOR_SOURCE_SIC_CODES)
    return queryset


def totals(scope):
    def compute():
        fields = [pollutant.key for pollutant in CRITERIA + TOXICS]
        row = records(scope).aggregate(
            facilities=Count('facility', distinct=True),
            **{field: Sum(field) for field in fields},
        )
        return {key: (value if key == 'facilities' else _float(value)) for key, value in row.items()}
    return cache.get_or_set(scope.key('totals'), compute, CACHE_TIMEOUT)


def _competition_ranks(pairs):
    """[(key, value), ...] sorted by value descending -> {key: rank}; ties share a rank."""
    result = {}
    previous = object()
    rank = 0
    for position, (key, value) in enumerate(pairs, 1):
        if value != previous:
            rank = position
            previous = value
        result[key] = rank
    return result


def ranks(scope):
    field = scope.pollutant.key

    def compute():
        pairs = (
            records(scope)
            .filter(**{f'{field}__gt': 0})
            .order_by(f'-{field}')
            .values_list('facility_id', field)
        )
        return _competition_ranks(pairs)
    return cache.get_or_set(scope.key('ranks'), compute, CACHE_TIMEOUT)


def with_ranks(rows, rank_map):
    return [(rank_map.get(record.facility_id), record) for record in rows]


def facility_table(scope, *, sector=None, district=None, city=None, q=None, sort='-value'):
    field = scope.pollutant.key
    queryset = (
        records(scope)
        .select_related('facility', 'facility__county', 'facility__city', 'facility__air_district')
        .annotate(value=F(field))
    )
    if sector:
        queryset = queryset.filter(facility__sector=sector)
    if district:
        queryset = queryset.filter(facility__air_district__external_id=district)
    if city:
        queryset = queryset.filter(facility__city__slug=city)
    if q:
        queryset = queryset.filter(facility__name__icontains=q)
    sort = sort if sort in SORTS else '-value'
    key = sort.lstrip('-')
    descending = sort.startswith('-')
    if key == 'value':
        order = F(field).desc(nulls_last=True) if descending else F(field).asc(nulls_last=True)
    else:
        order = F(SORT_FIELDS[key]).desc() if descending else F(SORT_FIELDS[key]).asc()
    return queryset.order_by(order, 'facility__name')


def sector_breakdown(scope):
    field = scope.pollutant.key

    def compute():
        rows = list(
            records(scope)
            .values('facility__sector')
            .annotate(facilities=Count('facility', distinct=True), value=Sum(field))
        )
        total = sum(float(row['value'] or 0) for row in rows)
        result = [{
            'sector': Facility.Sector(row['facility__sector']),
            'label': Facility.Sector(row['facility__sector']).label,
            'facilities': row['facilities'],
            'value': float(row['value'] or 0),
            'share': float(row['value'] or 0) / total if total else None,
        } for row in rows]
        result.sort(key=lambda row: (-row['value'], row['label']))
        return result
    return cache.get_or_set(scope.key('sectors'), compute, CACHE_TIMEOUT)


def county_breakdown(scope, *, sector=None):
    field = scope.pollutant.key
    everywhere = Scope(year=scope.year, county=None, pollutant=scope.pollutant, minor=scope.minor)

    def compute():
        queryset = records(everywhere)
        if sector:
            queryset = queryset.filter(facility__sector=sector)
        rows = list(
            queryset.values('facility__county')
            .annotate(facilities=Count('facility', distinct=True), value=Sum(field))
        )
        counties = Region.objects.in_bulk([row['facility__county'] for row in rows if row['facility__county']])
        total = sum(float(row['value'] or 0) for row in rows)
        result = [{
            'county': counties[row['facility__county']],
            'facilities': row['facilities'],
            'value': float(row['value'] or 0),
            'share': float(row['value'] or 0) / total if total else None,
        } for row in rows if row['facility__county'] in counties]
        result.sort(key=lambda row: (-row['value'], row['county'].name))
        return result
    return cache.get_or_set(everywhere.key('counties', sector or ''), compute, CACHE_TIMEOUT)


def by_year(scope, *, facility=None, sector=None):
    field = scope.pollutant.key

    def compute():
        if facility is not None:
            queryset = EmissionsRecord.objects.filter(facility=facility)
        else:
            queryset = records(scope, all_years=True)
            if sector:
                queryset = queryset.filter(facility__sector=sector)
        rows = queryset.values('year').annotate(value=Sum(field)).order_by('year')
        return [{'year': row['year'], 'value': float(row['value'] or 0)} for row in rows]
    extra = f'facility-{facility.pk}' if facility is not None else f'sector-{sector or ""}'
    return cache.get_or_set(scope.key('by-year', extra), compute, CACHE_TIMEOUT)


def sector_trends(scope):
    field = scope.pollutant.key

    def compute():
        rows = (
            records(scope, all_years=True)
            .values('facility__sector', 'year')
            .annotate(value=Sum(field))
            .order_by('facility__sector', 'year')
        )
        result = {}
        for row in rows:
            result.setdefault(row['facility__sector'], []).append(
                {'year': row['year'], 'value': float(row['value'] or 0)}
            )
        return result
    return cache.get_or_set(scope.key('sector-trends'), compute, CACHE_TIMEOUT)


def county_context(scope):
    """
    CARB's estimate of every source in the scope's counties, by source type,
    beside the permitted-facility total; None for toxics (CEPAM has none) or
    a year CEPAM hasn't been imported for.
    """
    if scope.toxics or scope.year is None:
        return None
    field = scope.pollutant.key

    def compute():
        counties = [scope.county] if scope.county else list(Region.objects.counties())
        sums = dict(
            CountyInventory.objects
            .filter(county__in=counties, year=scope.year, inventory=cepam.INVENTORY)
            .values_list('source_type')
            .annotate(total=Sum(field))
        )
        if not sums:
            return None
        parts = [{
            'source_type': source_type,
            'label': source_type.label,
            'tons': (sums.get(source_type) or 0) * 365,
        } for source_type in CountyInventory.SourceType]
        total = sum(part['tons'] for part in parts)
        if not total:
            return None
        for part in parts:
            part['share'] = part['tons'] / total
        facilities = totals(scope)[field] or 0
        return {
            'parts': parts,
            'total': total,
            'facilities': facilities,
            'facility_share': facilities / total,
            'base_year': cepam.BASE_YEAR,
            'inventory': cepam.INVENTORY,
            'counties': counties,
        }
    return cache.get_or_set(scope.key('context'), compute, CACHE_TIMEOUT)


def _rank_of(value, values):
    return 1 + sum(1 for other in values if other > value)


def facility_ranks(facility, year):
    """Criteria pollutants for one facility-year, ranked among its county's and its sector's facilities."""
    record = facility.emissions.filter(year=year).first()
    if record is None:
        return []
    fields = [pollutant.key for pollutant in CRITERIA]
    peers = EmissionsRecord.objects.filter(year=year)
    if not facility.is_minor_source:
        peers = peers.exclude(facility__sic_code__in=MINOR_SOURCE_SIC_CODES)
    county_rows = list(peers.filter(facility__county_id=facility.county_id).values(*fields))
    sector_rows = list(peers.filter(facility__sector=facility.sector).values(*fields))
    result = []
    for pollutant in CRITERIA:
        value = _float(getattr(record, pollutant.key))
        row = {'pollutant': pollutant, 'value': value}
        if value:
            county_values = [float(r[pollutant.key]) for r in county_rows if r[pollutant.key]]
            sector_values = [float(r[pollutant.key]) for r in sector_rows if r[pollutant.key]]
            county_total = sum(county_values)
            row.update({
                'county_rank': _rank_of(value, county_values),
                'county_count': len(county_values),
                'sector_rank': _rank_of(value, sector_values),
                'sector_count': len(sector_values),
                'county_share': value / county_total if county_total else None,
            })
        result.append(row)
    return result


def facility_toxics(facility, year):
    """Toxics the facility reported in `year`, in lbs/yr, with the year before when it has one."""
    current = facility.emissions.filter(year=year).first()
    if current is None:
        return []
    previous = facility.emissions.filter(year=year - 1).first()
    rows = []
    for pollutant in TOXICS:
        value = getattr(current, pollutant.key)
        if not value:
            continue
        rows.append({
            'pollutant': pollutant,
            'value': pollutant.display(value),
            'previous': pollutant.display(getattr(previous, pollutant.key)) if previous else None,
            'previous_year': previous.year if previous else None,
        })
    return rows


def large_changes(facility):
    """Consecutive-year criteria changes larger than LARGE_CHANGE, oldest first."""
    history = list(facility.emissions.order_by('year'))
    changes = []
    for before, after in zip(history, history[1:]):
        if after.year != before.year + 1:
            continue
        for pollutant in CRITERIA:
            old = _float(getattr(before, pollutant.key))
            new = _float(getattr(after, pollutant.key))
            if not old or new is None:
                continue
            pct = (new - old) / old
            if abs(pct) > LARGE_CHANGE:
                changes.append({
                    'pollutant': pollutant,
                    'year': after.year,
                    'previous_year': before.year,
                    'pct': pct * 100,
                })
    return changes
```

- [ ] **Step 4: Run the tests**

Run: `$TEST camp/apps/emissions/tests/test_stats.py`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add camp/apps/emissions/pollutants.py camp/apps/emissions/stats.py camp/apps/emissions/tests/test_stats.py
git commit -m "feat(emissions): pollutant registry and scope-cached aggregates"
```

---
### Task 6: Explorer pages

Every page except the map: landing, facility list (+ CSV), facility detail, sector list and detail, about. They land together because the landing already links to all of them.

**Files:**
- Modify: `camp/apps/emissions/models.py` (`Facility.get_absolute_url`)
- Create: `camp/apps/emissions/templatetags/__init__.py`, `camp/apps/emissions/templatetags/emissions_explorer.py`
- Create: `camp/apps/emissions/views.py`, `camp/apps/emissions/urls.py`
- Modify: `camp/urls.py:37` (mount at `tools/emissions/`)
- Create: `camp/templates/emissions/base.html`, `home.html`, `facility-list.html`, `facility-detail.html`, `sector-list.html`, `sector-detail.html`, `about.html`
- Create: `camp/templates/emissions/includes/scope-picker.html`, `facility-table.html`, `context-bar.html`, `sector-rows.html`
- Create: `assets/sass/sjvair/pages/emissions.sass`; modify `assets/sass/style.sass` (import after pesticides)
- Test: `camp/apps/emissions/tests/test_views.py`, `camp/apps/emissions/tests/test_templatetags.py`

**Interfaces:**
- Consumes: everything in `stats` and `pollutants` (Task 5); `sectors.sector_description`, `sectors.sic_title` (Task 3); pesticides' `qs_replace`, `sort_link`, `elided_page_range` template tags (`{% load pesticides_explorer %}`), `pesticides/includes/trend-chart.html`, `pesticides/includes/pagination.html`, `js/pesticides/charts.js`, `js/pesticides/explorer.js`.
- Produces: URL names `emissions:home`, `emissions:about`, `emissions:facility-list`, `emissions:facility-redirect` (`sqid`), `emissions:facility-detail` (`sqid`, `slug`), `emissions:sector-list`, `emissions:sector-detail` (`sector`); `Facility.get_absolute_url()`; `views.ScopeMixin` (context keys `scope, year, year_options, county, county_options, pollutant, pollutant_options, toxics, minor, scope_qs, scope_params, section`); template blocks in `emissions/base.html`: `explorer-lede`, `breadcrumbs`, `breadcrumb-list`, `explorer-content`, and `explorer-tabs-start` (an empty block at the start of the tab list, where Task 7 adds the Map tab); template tag library `emissions_explorer` with filters `amount`, `percent`, `width_pct`, `signed_pct` and tags `emissions_trend_chart`, `sparkline`, `sector_description`, `sic_title`.

- [ ] **Step 1: Write the failing tests**

Create `camp/apps/emissions/tests/test_templatetags.py`:

```python
from django.test import TestCase

from camp.apps.emissions.pollutants import POLLUTANTS
from camp.apps.emissions.templatetags import emissions_explorer as tags


class AmountTests(TestCase):
    def test_tons(self):
        nox = POLLUTANTS['nox']
        assert tags.amount(1456.4, nox) == '1,456'
        assert tags.amount(8.25, nox) == '8.2'
        assert tags.amount(0.25, nox) == '0.25'
        assert tags.amount(0.001, nox) == '<0.01'
        assert tags.amount(0, nox) == '0'
        assert tags.amount(None, nox) == '—'

    def test_toxics_convert_to_lbs(self):
        assert tags.amount(0.001, POLLUTANTS['benzene']) == '2.0'


class PercentTests(TestCase):
    def test_percent(self):
        assert tags.percent(0.123) == '12%'
        assert tags.percent(0.004) == '<1%'
        assert tags.percent(0) == '0%'
        assert tags.percent(None) == '—'
        assert tags.width_pct(0.12345) == '12.35%'
        assert tags.signed_pct(100.0) == '+100%'
        assert tags.signed_pct(-62.4) == '−62%'


class TrendChartTests(TestCase):
    def test_chart_payload_and_sentence(self):
        context = tags.emissions_trend_chart(
            [{'year': 2024, 'value': 6.0}, {'year': 2023, 'value': 3.0}], POLLUTANTS['nox'], 2024,
        )
        assert context['chart']['x'] == [2023, 2024]
        assert context['chart']['y'] == [3.0, 6.0]
        assert context['chart']['selected'] == 2024
        assert context['sentence'] == 'Up 100% from 2023'
        assert context['title'] == 'NOx by year (tons/yr)'

    def test_empty(self):
        assert tags.emissions_trend_chart([], POLLUTANTS['nox'])['has_data'] is False


class SparklineTests(TestCase):
    def test_sparkline(self):
        svg = tags.sparkline([{'year': 2023, 'value': 1.0}, {'year': 2024, 'value': 2.0}])
        assert svg.startswith('<svg class="sparkline"')
        assert '<polyline points="0.0,12.0 100.0,2.0"' in svg
        assert tags.sparkline([{'year': 2024, 'value': 1.0}]) == ''
```

Create `camp/apps/emissions/tests/test_views.py`:

```python
import csv
import io

from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from camp.apps.emissions import cepam
from camp.apps.emissions.models import CountyInventory, EmissionsRecord, Facility
from camp.apps.regions.models import Region


class ViewTestCase(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        cache.clear()
        self.plant = Facility.objects.get(name='TEST PLANT')
        self.cement = Facility.objects.get(name='TEST CEMENT')

    def get(self, name, *args, params=None, status=200):
        response = self.client.get(reverse(f'emissions:{name}', args=args), params or {})
        assert response.status_code == status, (name, params, response.status_code)
        return response


class HomeTests(ViewTestCase):
    def test_renders_for_every_scope(self):
        for params in ({}, {'year': 2023}, {'county': 'fresno'}, {'county': 'kern', 'toxics': 1},
                       {'minor': 1}, {'pollutant': 'pm'}, {'year': 1900, 'pollutant': 'bogus'}):
            self.get('home', params=params)

    def test_top_facilities_and_totals(self):
        response = self.get('home')
        content = response.content.decode()
        assert 'TEST CEMENT' in content
        assert 'TEST GAS STATION' not in content
        assert '106' in content

    def test_context_bar_when_carb_estimates_exist(self):
        fresno = Region.objects.get(type=Region.Type.COUNTY, slug='fresno')
        CountyInventory.objects.create(county=fresno, year=2024, inventory=cepam.INVENTORY,
                                       source_type='mobile', eic='723', nox=1.0)
        response = self.get('home', params={'county': 'fresno'})
        assert 'CARB estimates all sources' in response.content.decode()

    def test_no_context_bar_without_estimates(self):
        assert 'CARB estimates all sources' not in self.get('home').content.decode()


class FacilityListTests(ViewTestCase):
    def test_filters_and_sort(self):
        assert 'TEST PLANT' in self.get('facility-list', params={'q': 'plant'}).content.decode()
        assert 'TEST CEMENT' not in self.get('facility-list', params={'q': 'plant'}).content.decode()
        assert 'TEST PLANT' not in self.get('facility-list', params={'sector': 'cement-minerals'}).content.decode()
        self.get('facility-list', params={'sort': 'name', 'district': 'KER', 'city': 'fresno', 'page': 99})

    def test_minor_sources_only_when_asked(self):
        assert 'TEST GAS STATION' not in self.get('facility-list').content.decode()
        assert 'TEST GAS STATION' in self.get('facility-list', params={'minor': 1, 'pollutant': 'rog'}).content.decode()

    def test_csv(self):
        response = self.get('facility-list', params={'format': 'csv'})
        assert response['Content-Type'] == 'text/csv'
        assert 'facility-emissions-2024.csv' in response['Content-Disposition']
        rows = list(csv.DictReader(io.StringIO(response.content.decode())))
        assert [row['facility'] for row in rows] == ['TEST CEMENT', 'TEST PLANT']
        assert rows[0]['rank'] == '1'
        assert rows[0]['air_district'] == 'Eastern Kern APCD'
        assert float(rows[0]['nox_tons']) == 100.0
        assert float(rows[1]['benzene_lbs']) == 2.0

    def test_queries_do_not_grow_with_rows(self):
        self.get('facility-list')
        with CaptureQueriesContext(connection) as small:
            self.get('facility-list')
        sju = Region.objects.get(pk=9001)
        for i in range(20):
            facility = Facility.objects.create(county_code=10, air_district=sju, facid=100 + i, name=f'EXTRA {i}',
                                               county=self.plant.county, sic_code=4911, sector='power-plants')
            EmissionsRecord.objects.create(facility=facility, year=2024, nox=i + 1)
        cache.clear()
        self.get('facility-list')
        with CaptureQueriesContext(connection) as large:
            self.get('facility-list')
        assert len(large) == len(small)


class FacilityDetailTests(ViewTestCase):
    def detail(self, facility, params=None, status=200):
        response = self.client.get(facility.get_absolute_url(), params or {})
        assert response.status_code == status
        return response.content.decode()

    def test_page(self):
        content = self.detail(self.plant)
        assert 'TEST PLANT' in content
        assert 'Regulated by' in content and 'San Joaquin Valley APCD' in content
        assert 'Report an air pollution problem' in content
        assert 'Glass manufacturing' in content
        assert 'SIC 3221' in content and 'Glass Containers' in content
        assert 'Benzene' in content
        assert 'how emissions are estimated' in content

    def test_eastern_kern_has_phone_but_no_complaints_link(self):
        content = self.detail(self.cement)
        assert 'Eastern Kern APCD' in content
        assert '(661) 862-5250' in content
        assert 'Report an air pollution problem' not in content

    def test_falls_back_to_the_latest_reported_year(self):
        content = self.detail(self.cement, params={'year': 2023})
        assert 'no emissions reported for 2023' in content

    def test_every_pollutant_toggle(self):
        for pollutant in ('nox', 'rog', 'pm', 'pm10', 'sox', 'co', 'tog'):
            self.detail(self.plant, params={'pollutant': pollutant})

    def test_wrong_slug_redirects_to_the_canonical_url(self):
        url = reverse('emissions:facility-detail', args=[self.plant.sqid, 'wrong'])
        response = self.client.get(url, {'year': 2023})
        assert response.status_code == 301
        assert response['Location'] == self.plant.get_absolute_url() + '?year=2023'

    def test_bare_sqid_redirects(self):
        response = self.client.get(reverse('emissions:facility-redirect', args=[self.plant.sqid]))
        assert response.status_code == 301
        assert response['Location'] == self.plant.get_absolute_url()

    def test_unknown_sqid_is_404(self):
        assert self.client.get(reverse('emissions:facility-detail', args=['nope', 'x'])).status_code == 404
        assert self.client.get(reverse('emissions:facility-redirect', args=['nope'])).status_code == 404


class SectorTests(ViewTestCase):
    def test_list(self):
        content = self.get('sector-list').content.decode()
        assert 'Cement, concrete &amp; minerals' in content
        assert '<svg class="sparkline"' in content

    def test_detail(self):
        content = self.get('sector-detail', 'glass').content.decode()
        assert 'Glass manufacturing' in content
        assert 'TEST PLANT' in content
        assert 'TEST CEMENT' not in content

    def test_unknown_sector_is_404(self):
        self.get('sector-detail', 'nope', status=404)


class AboutTests(ViewTestCase):
    def test_about(self):
        content = self.get('about').content.decode()
        assert 'Total PM' in content
        assert 'Eastern Kern' in content
        assert 'id="carb-estimates"' in content
        assert 'id="minor-sources"' in content
```

Run: `$TEST camp/apps/emissions/tests/test_templatetags.py camp/apps/emissions/tests/test_views.py`
Expected: ERROR (`No module named 'camp.apps.emissions.templatetags'` / `NoReverseMatch`).

- [ ] **Step 2: `Facility.get_absolute_url`**

In `camp/apps/emissions/models.py` add `from django.urls import reverse` and `from django.utils.text import slugify`, and on `Facility`:

```python
    def get_absolute_url(self):
        return reverse('emissions:facility-detail', kwargs={
            'sqid': self.sqid,
            'slug': slugify(self.name) or 'facility',
        })
```

- [ ] **Step 3: Template tags**

Create `camp/apps/emissions/templatetags/__init__.py` (empty) and `camp/apps/emissions/templatetags/emissions_explorer.py`:

```python
import uuid

from django import template
from django.utils.html import format_html

from camp.apps.emissions import sectors

register = template.Library()


@register.filter
def amount(tons, pollutant):
    """A pollutant amount in its display unit: '1,456', '8.2', '0.25', '<0.01', '—'."""
    value = pollutant.display(tons)
    if value is None:
        return '—'
    size = abs(value)
    if size and size < 0.01:
        return '<0.01'
    digits = 2 if size and size < 1 else (1 if size and size < 10 else 0)
    return f'{value:,.{digits}f}'


@register.filter
def percent(share):
    if share is None:
        return '—'
    if 0 < share < 0.01:
        return '<1%'
    return f'{share * 100:.0f}%'


@register.filter
def width_pct(share):
    """A CSS width for a share bar."""
    return f'{(share or 0) * 100:.2f}%'


@register.filter
def signed_pct(pct):
    return f'+{pct:.0f}%' if pct >= 0 else f'−{abs(pct):.0f}%'


@register.simple_tag
def sector_description(sector):
    return sectors.sector_description(sector)


@register.simple_tag
def sic_title(sic):
    return sectors.sic_title(sic)


def _change_sentence(by_year, year):
    if year is None or year not in by_year or (year - 1) not in by_year or not by_year[year - 1]:
        return ''
    pct = (by_year[year] - by_year[year - 1]) / by_year[year - 1] * 100
    if abs(pct) < 0.5:
        return f'Unchanged from {year - 1}'
    return f"{'Up' if pct > 0 else 'Down'} {abs(pct):.0f}% from {year - 1}"


@register.inclusion_tag('pesticides/includes/trend-chart.html')
def emissions_trend_chart(points, pollutant, year=None, title=None):
    """
    The by-year trend, drawn by js/pesticides/charts.js from the payload this
    embeds (same markup and chart type as the pesticides trend).
    """
    rows = sorted(points, key=lambda row: row['year'])
    years = [row['year'] for row in rows]
    values = [pollutant.display(row['value']) or 0 for row in rows]
    return {
        'chart_id': f'chart-{uuid.uuid4().hex[:8]}',
        'chart': {
            'type': 'line',
            'unit': pollutant.unit,
            'x': years,
            'y': values,
            'selected': year if year in years else None,
        },
        'has_data': bool(rows),
        'title': title or f'{pollutant.label} by year ({pollutant.unit}/yr)',
        'sentence': _change_sentence(dict(zip(years, values)), year),
        'first_year': years[0] if years else None,
        'last_year': years[-1] if years else None,
    }


@register.simple_tag
def sparkline(points, width=100, height=24):
    """A tiny inline SVG trend line; '' with fewer than two points."""
    values = [row['value'] for row in sorted(points, key=lambda row: row['year'])]
    if len(values) < 2:
        return ''
    top = max(values) or 1
    step = width / (len(values) - 1)
    coords = ' '.join(
        f'{i * step:.1f},{height - 2 - (value / top) * (height - 4):.1f}'
        for i, value in enumerate(values)
    )
    return format_html(
        '<svg class="sparkline" viewBox="0 0 {w} {h}" width="{w}" height="{h}" aria-hidden="true">'
        '<polyline points="{coords}"/></svg>',
        w=width, h=height, coords=coords,
    )
```

- [ ] **Step 4: Views and URLs**

Create `camp/apps/emissions/views.py`:

```python
import csv

from django.core.paginator import Paginator
from django.http import Http404, HttpResponse
from django.shortcuts import redirect

import vanilla

from camp.apps.emissions import stats
from camp.apps.emissions.models import Facility
from camp.apps.emissions.pollutants import CRITERIA, TOXICS
from camp.apps.regions.models import Region

PAGE_SIZE = 50
SECTOR_PAGE_ROWS = 25


class ScopeMixin:
    """Resolves the explorer scope (year, county, pollutant, toxics, minor) and puts the scope bar's context on every page."""

    section = None
    hide_scope = False

    def get_scope(self):
        if not hasattr(self, '_scope'):
            self._scope = stats.resolve_scope(self.request.GET)
        return self._scope

    def get_context_data(self, **kwargs):
        scope = self.get_scope()
        context = {
            'scope': scope,
            'year': scope.year,
            'year_options': stats.available_years(),
            'county': scope.county,
            'county_options': list(Region.objects.counties().order_by('name').values_list('slug', 'name')),
            'pollutant': scope.pollutant,
            'pollutant_options': TOXICS if scope.toxics else CRITERIA,
            'toxics': scope.toxics,
            'minor': scope.minor,
            'scope_qs': scope.query(),
            'scope_params': scope.params(),
            'section': self.section,
            'hide_scope': self.hide_scope,
        }
        context.update(kwargs)
        return super().get_context_data(**context)


def list_filters(get):
    """The facility table's own filters (beyond the scope), validated."""
    sector = get.get('sector')
    sort = get.get('sort')
    return {
        'sector': sector if sector in Facility.Sector.values else None,
        'district': get.get('district') or None,
        'city': get.get('city') or None,
        'q': (get.get('q') or '').strip() or None,
        'sort': sort if sort in stats.SORTS else '-value',
    }


class Home(ScopeMixin, vanilla.TemplateView):
    template_name = 'emissions/home.html'

    def get_context_data(self, **kwargs):
        scope = self.get_scope()
        totals = stats.totals(scope)
        return super().get_context_data(
            totals=totals,
            total=totals[scope.pollutant.key],
            context_bar=stats.county_context(scope),
            top_rows=stats.with_ranks(stats.facility_table(scope)[:10], stats.ranks(scope)),
            top_sectors=stats.sector_breakdown(scope)[:6],
            by_year=stats.by_year(scope),
            **kwargs,
        )


class About(ScopeMixin, vanilla.TemplateView):
    template_name = 'emissions/about.html'
    section = 'about'
    hide_scope = True


class FacilityList(ScopeMixin, vanilla.TemplateView):
    template_name = 'emissions/facility-list.html'
    section = 'facilities'

    def get(self, request, *args, **kwargs):
        if request.GET.get('format') == 'csv':
            return self.csv_response()
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        scope = self.get_scope()
        filters = list_filters(self.request.GET)
        page = Paginator(stats.facility_table(scope, **filters), PAGE_SIZE).get_page(self.request.GET.get('page'))
        return super().get_context_data(
            rows=stats.with_ranks(page.object_list, stats.ranks(scope)),
            page_obj=page,
            is_paginated=page.has_other_pages(),
            sort=filters['sort'],
            filters=filters,
            sector_options=Facility.Sector.choices,
            district_options=(
                Region.objects.filter(type=Region.Type.AIR_DISTRICT, district_facilities__isnull=False)
                .distinct().order_by('name')
            ),
            **kwargs,
        )

    def csv_response(self):
        scope = self.get_scope()
        rank_map = stats.ranks(scope)
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="facility-emissions-{scope.year}.csv"'
        writer = csv.writer(response)
        writer.writerow(
            ['rank', 'facility', 'id', 'air_district', 'county', 'city', 'sector', 'sic_code', 'year']
            + [f'{pollutant.key}_tons' for pollutant in CRITERIA]
            + [f'{pollutant.key}_lbs' for pollutant in TOXICS]
        )
        for record in stats.facility_table(scope, **list_filters(self.request.GET)):
            facility = record.facility
            values = [pollutant.display(getattr(record, pollutant.key)) for pollutant in CRITERIA + TOXICS]
            writer.writerow(
                [rank_map.get(record.facility_id, ''), facility.name, facility.sqid, facility.air_district.name,
                 facility.get_county() or '', facility.get_city(), facility.get_sector_display(),
                 facility.sic_code or '', record.year]
                + ['' if value is None else value for value in values]
            )
        return response


def get_facility(sqid):
    facility = Facility.objects.filter(sqid=sqid).first()
    if facility is None:
        raise Http404('No such facility.')
    return facility


class FacilityRedirect(vanilla.View):
    """`facilities/<sqid>/` -> the slugged URL, keeping the query string."""

    def get(self, request, sqid):
        facility = get_facility(sqid)
        query = request.GET.urlencode()
        return redirect(facility.get_absolute_url() + (f'?{query}' if query else ''), permanent=True)


class FacilityDetail(ScopeMixin, vanilla.TemplateView):
    template_name = 'emissions/facility-detail.html'
    section = 'facilities'

    def get(self, request, sqid, slug):
        self.facility = get_facility(sqid)
        if request.path != self.facility.get_absolute_url():
            query = request.GET.urlencode()
            return redirect(self.facility.get_absolute_url() + (f'?{query}' if query else ''), permanent=True)
        return super().get(request, sqid=sqid, slug=slug)

    def get_context_data(self, **kwargs):
        scope = self.get_scope()
        facility = self.facility
        record = facility.emissions.filter(year=scope.year).first() or facility.emissions.order_by('-year').first()
        shown_year = record.year if record else scope.year
        return super().get_context_data(
            facility=facility,
            district=facility.air_district,
            shown_year=shown_year,
            ranks=stats.facility_ranks(facility, shown_year),
            trend=stats.by_year(scope, facility=facility),
            toxics_rows=stats.facility_toxics(facility, shown_year),
            changes=stats.large_changes(facility),
            criteria=CRITERIA,
            **kwargs,
        )


class SectorList(ScopeMixin, vanilla.TemplateView):
    template_name = 'emissions/sector-list.html'
    section = 'sectors'

    def get_context_data(self, **kwargs):
        scope = self.get_scope()
        trends = stats.sector_trends(scope)
        rows = [dict(row, trend=trends.get(row['sector'], [])) for row in stats.sector_breakdown(scope)]
        return super().get_context_data(rows=rows, **kwargs)


class SectorDetail(ScopeMixin, vanilla.TemplateView):
    template_name = 'emissions/sector-detail.html'
    section = 'sectors'

    def get(self, request, sector):
        if sector not in Facility.Sector.values:
            raise Http404('No such sector.')
        self.sector = Facility.Sector(sector)
        return super().get(request, sector=sector)

    def get_context_data(self, **kwargs):
        scope = self.get_scope()
        summary = next((row for row in stats.sector_breakdown(scope) if row['sector'] == self.sector), None)
        table = stats.facility_table(scope, sector=self.sector)
        return super().get_context_data(
            sector=self.sector,
            summary=summary,
            trend=stats.by_year(scope, sector=self.sector),
            counties=stats.county_breakdown(scope, sector=self.sector),
            rows=stats.with_ranks(table[:SECTOR_PAGE_ROWS], stats.ranks(scope)),
            facility_count=table.count(),
            **kwargs,
        )
```

Create `camp/apps/emissions/urls.py`:

```python
from django.urls import path

from camp.apps.emissions import views

urlpatterns = [
    path('', views.Home.as_view(), name='home'),
    path('about/', views.About.as_view(), name='about'),
    path('facilities/', views.FacilityList.as_view(), name='facility-list'),
    path('facilities/<str:sqid>/', views.FacilityRedirect.as_view(), name='facility-redirect'),
    path('facilities/<str:sqid>/<slug:slug>/', views.FacilityDetail.as_view(), name='facility-detail'),
    path('sectors/', views.SectorList.as_view(), name='sector-list'),
    path('sectors/<slug:sector>/', views.SectorDetail.as_view(), name='sector-detail'),
]
```

In `camp/urls.py`, after the `tools/pesticides/` line:

```python
    path('tools/emissions/', include(('camp.apps.emissions.urls', 'emissions'), namespace='emissions')),
```

- [ ] **Step 5: Base template and scope bar**

Create `camp/templates/emissions/base.html`:

```django
{% extends 'page.html' %}
{% load static %}

{% block title %}Facility Emissions | {{ block.super }}{% endblock %}
{# The explorer chrome (scope bar, tabs, tables, charts) is styled under body.pesticides; emissions-only styles are under body.emissions. #}
{% block body-class %}pesticides emissions{% endblock %}

{% block extra-head %}{% endblock %}

{% block javascripts %}
<script src="{% static 'htmx/htmx.min.js' %}"></script>
<script src="{% static 'uplot/uPlot.iife.min.js' %}"></script>
<script src="{% static 'js/pesticides/charts.js' %}"></script>
<script src="{% static 'js/pesticides/explorer.js' %}"></script>
{% endblock %}

{% block main %}
<div id="explorer"
    hx-boost="true"
    hx-target="#explorer-body"
    hx-select="#explorer-body"
    hx-select-oob="#explorer-tabs"
    hx-swap="outerHTML"
    hx-push-url="true"
    hx-indicator="body">
<section class="section is-small hook" id="explorer-hero">
    <div class="container">
        <div class="content">
            <h1 class="is-size-2 mb-1"><a href="{% url 'emissions:home' %}">Facility Emissions Explorer</a></h1>
            {% block explorer-lede %}{% endblock %}
        </div>
        <div class="tabs is-boxed explorer-nav">
            <ul id="explorer-tabs">
                {% block explorer-tabs-start %}{% endblock %}
                <li class="{% if section == 'facilities' %}is-active{% endif %}"><a href="{% url 'emissions:facility-list' %}{{ scope_qs }}" title="Facilities"><span class="icon is-small"><span class="fa-duotone fa-fw fa-industry explorer-icon" aria-hidden="true"></span></span><span class="tab-label">Facilities</span></a></li>
                <li class="{% if section == 'sectors' %}is-active{% endif %}"><a href="{% url 'emissions:sector-list' %}{{ scope_qs }}" title="Sectors"><span class="icon is-small"><span class="fa-duotone fa-fw fa-layer-group explorer-icon" aria-hidden="true"></span></span><span class="tab-label">Sectors</span></a></li>
                <li class="{% if section == 'about' %}is-active{% endif %}"><a href="{% url 'emissions:about' %}" title="About the data"><span class="icon is-small"><span class="fa-duotone fa-fw fa-circle-info explorer-icon" aria-hidden="true"></span></span><span class="tab-label">About</span></a></li>
            </ul>
        </div>
    </div>
</section>

<div id="explorer-body">
<section class="breadcrumbs explorer-scope-bar">
    <div class="container">
        <div class="explorer-scope">
            {% block breadcrumbs %}
            <nav class="breadcrumb" aria-label="breadcrumbs">
                <ul>
                    <li><a href="{% url 'emissions:home' %}{{ scope_qs }}">Emissions</a></li>
                    {% block breadcrumb-list %}{% endblock %}
                </ul>
            </nav>
            {% endblock %}
            {% include 'emissions/includes/scope-picker.html' %}
        </div>
    </div>
</section>

<section class="section">
    <div class="container">
        {% block explorer-content %}{% endblock %}
    </div>
</section>
</div>
</div>
{% endblock %}
```

Create `camp/templates/emissions/includes/scope-picker.html` (same dropdown markup and classes as `pesticides/includes/scope-picker.html`, so `explorer.js` opens and closes them):

```django
{% load pesticides_explorer %}
{% comment %}
The explorer scope: year, county and pollutant dropdowns, then two toggles
(toxic air contaminants; include minor sources). Each option is a link that
keeps the rest of the query string minus the page number. Hidden on pages
the scope doesn't apply to (hide_scope).
{% endcomment %}
{% if not hide_scope %}
<div class="explorer-scope-pickers">
    {% if year_options|length > 1 %}
    <div class="dropdown is-right explorer-scope-picker" data-scope="year">
        <div class="dropdown-trigger">
            <button type="button" class="button is-small" aria-haspopup="true" aria-expanded="false" aria-label="Year: {{ year }}">
                <span class="icon"><span class="fa-duotone fa-fw fa-calendar explorer-icon is-scope" aria-hidden="true"></span></span>
                <span class="explorer-scope-label">{{ year }}</span>
                <span class="icon is-small"><span class="fa-regular fa-chevron-down" aria-hidden="true"></span></span>
            </button>
        </div>
        <div class="dropdown-menu" role="menu">
            <div class="dropdown-content explorer-scope-years">
                {% for option in year_options reversed %}
                <a class="dropdown-item{% if option == year %} is-active{% endif %}" href="{% qs_replace year=option page=None %}"{% if option == year %} aria-current="page"{% endif %}>{{ option }}</a>
                {% endfor %}
            </div>
        </div>
    </div>
    {% endif %}
    {% if county_options %}
    <div class="dropdown is-right explorer-scope-picker" data-scope="county">
        <div class="dropdown-trigger">
            <button type="button" class="button is-small" aria-haspopup="true" aria-expanded="false" aria-label="County: {% if county %}{{ county.name }}{% else %}all counties{% endif %}">
                <span class="icon"><span class="fa-duotone fa-fw fa-map explorer-icon is-scope" aria-hidden="true"></span></span>
                <span class="explorer-scope-label">{% if county %}{{ county.name|cut:" County" }}{% else %}All counties{% endif %}</span>
                <span class="icon is-small"><span class="fa-regular fa-chevron-down" aria-hidden="true"></span></span>
            </button>
        </div>
        <div class="dropdown-menu" role="menu">
            <div class="dropdown-content">
                <a class="dropdown-item{% if not county %} is-active{% endif %}" href="{% qs_replace county=None page=None %}">All counties</a>
                <hr class="dropdown-divider">
                {% for slug, name in county_options %}
                <a class="dropdown-item{% if county and county.slug == slug %} is-active{% endif %}" href="{% qs_replace county=slug page=None %}">{{ name|cut:" County" }}</a>
                {% endfor %}
            </div>
        </div>
    </div>
    {% endif %}
    <div class="dropdown is-right explorer-scope-picker" data-scope="pollutant">
        <div class="dropdown-trigger">
            <button type="button" class="button is-small" aria-haspopup="true" aria-expanded="false" aria-label="Pollutant: {{ pollutant.name }}">
                <span class="icon"><span class="fa-duotone fa-fw fa-smoke explorer-icon is-scope" aria-hidden="true"></span></span>
                <span class="explorer-scope-label">{{ pollutant.label }}</span>
                <span class="icon is-small"><span class="fa-regular fa-chevron-down" aria-hidden="true"></span></span>
            </button>
        </div>
        <div class="dropdown-menu" role="menu">
            <div class="dropdown-content">
                {% for option in pollutant_options %}
                <a class="dropdown-item{% if option.key == pollutant.key %} is-active{% endif %}" href="{% qs_replace pollutant=option.key page=None %}">{{ option.label }}{% if option.label != option.name %} <span class="has-text-grey">{{ option.name }}</span>{% endif %}</a>
                {% endfor %}
            </div>
        </div>
    </div>
    <a class="button is-small explorer-scope-toggle{% if toxics %} is-set{% endif %}" role="button"
       href="{% if toxics %}{% qs_replace toxics=None pollutant=None page=None %}{% else %}{% qs_replace toxics=1 pollutant=None page=None %}{% endif %}"
       aria-pressed="{% if toxics %}true{% else %}false{% endif %}">
        <span class="icon">{% if toxics %}<span class="fa-regular fa-check" aria-hidden="true"></span>{% else %}<span class="fa-duotone fa-fw fa-skull-crossbones explorer-icon" aria-hidden="true"></span>{% endif %}</span>
        <span class="explorer-scope-label">Toxic air contaminants</span>
    </a>
    <a class="button is-small explorer-scope-toggle{% if minor %} is-set{% endif %}" role="button"
       href="{% if minor %}{% qs_replace minor=None page=None %}{% else %}{% qs_replace minor=1 page=None %}{% endif %}"
       aria-pressed="{% if minor %}true{% else %}false{% endif %}">
        <span class="icon">{% if minor %}<span class="fa-regular fa-check" aria-hidden="true"></span>{% else %}<span class="fa-duotone fa-fw fa-gas-pump explorer-icon" aria-hidden="true"></span>{% endif %}</span>
        <span class="explorer-scope-label">Include minor sources</span>
    </a>
</div>
{% endif %}
```

- [ ] **Step 6: Shared includes**

`camp/templates/emissions/includes/facility-table.html` (`rows` = `[(rank, record), ...]`, `sortable` = whether headers sort):

```django
{% load emissions_explorer pesticides_explorer %}
<div class="table-container">
<table class="table is-fullwidth is-hoverable is-narrow facility-table">
    <thead>
        <tr>
            <th class="has-text-right">Rank</th>
            <th>{% if sortable %}{% sort_link 'name' 'Facility' %}{% else %}Facility{% endif %}</th>
            <th>City</th>
            <th>{% if sortable %}{% sort_link 'county' 'County' %}{% else %}County{% endif %}</th>
            <th>Sector</th>
            {% with heading=pollutant.label|add:" ("|add:pollutant.unit|add:"/yr)" %}
            <th class="has-text-right">{% if sortable %}{% sort_link 'value' heading %}{% else %}{{ heading }}{% endif %}</th>
            {% endwith %}
        </tr>
    </thead>
    <tbody>
        {% for rank, record in rows %}
        {% with facility=record.facility %}
        <tr{% if facility.is_minor_source %} class="is-minor"{% endif %}>
            <td class="has-text-right">{{ rank|default:"—" }}</td>
            <td><a href="{{ facility.get_absolute_url }}{{ scope_qs }}">{{ facility.name }}</a></td>
            <td>{% if facility.city %}{{ facility.city.name }}{% else %}{{ facility.address.city|title }}{% endif %}</td>
            <td>{{ facility.county.name|cut:" County" }}</td>
            <td><a href="{% url 'emissions:sector-detail' facility.sector %}{{ scope_qs }}">{{ facility.get_sector_display }}</a></td>
            <td class="has-text-right">{{ record.value|amount:pollutant }}</td>
        </tr>
        {% endwith %}
        {% empty %}
        <tr><td colspan="6">No facilities match.</td></tr>
        {% endfor %}
    </tbody>
</table>
</div>
```

`camp/templates/emissions/includes/context-bar.html`:

```django
{% load emissions_explorer %}
<div class="box emissions-context">
    <p>Permitted facilities in this inventory reported about <strong>{{ context_bar.facilities|amount:pollutant }} tons</strong> of {{ pollutant.label }} in {{ year }}.
       CARB estimates all sources in {% if county %}{{ county.name }}{% else %}these counties{% endif %} emit about
       <strong>{{ context_bar.total|amount:pollutant }} tons</strong> a year (projected from its {{ context_bar.base_year }} inventory).</p>
    <div class="emissions-context-bar" role="img" aria-label="{% for part in context_bar.parts %}{{ part.label }} {{ part.share|percent }}{% if not forloop.last %}, {% endif %}{% endfor %}">
        {% for part in context_bar.parts %}{% if part.share %}<span class="segment is-{{ part.source_type }}" style="width: {{ part.share|width_pct }}" title="{{ part.label }}: {{ part.share|percent }}"></span>{% endif %}{% endfor %}
    </div>
    <p class="emissions-legend">
        {% for part in context_bar.parts %}<span><span class="swatch is-{{ part.source_type }}"></span>{{ part.label }} {{ part.share|percent }}</span>{% endfor %}
    </p>
    <p class="is-size-7"><a href="{% url 'emissions:about' %}#carb-estimates">How CARB estimates all sources</a></p>
</div>
```

`camp/templates/emissions/includes/sector-rows.html` (`rows` from `stats.sector_breakdown`, optionally with `trend`):

```django
{% load emissions_explorer %}
<div class="table-container">
<table class="table is-fullwidth is-narrow sector-table">
    <thead>
        <tr><th>Sector</th><th class="has-text-right">Facilities</th><th class="has-text-right">{{ pollutant.label }} ({{ pollutant.unit }}/yr)</th><th>Share</th>{% if show_trend %}<th>Trend</th>{% endif %}</tr>
    </thead>
    <tbody>
        {% for row in rows %}
        <tr>
            <td><a href="{% url 'emissions:sector-detail' row.sector %}{{ scope_qs }}">{{ row.label }}</a>{% if show_description %}<br><span class="is-size-7 has-text-grey">{% sector_description row.sector %}</span>{% endif %}</td>
            <td class="has-text-right">{{ row.facilities }}</td>
            <td class="has-text-right">{{ row.value|amount:pollutant }}</td>
            <td><div class="share-bar" title="{{ row.share|percent }}"><span style="width: {{ row.share|width_pct }}"></span></div>{{ row.share|percent }}</td>
            {% if show_trend %}<td>{% sparkline row.trend %}</td>{% endif %}
        </tr>
        {% endfor %}
    </tbody>
</table>
</div>
```

- [ ] **Step 7: Page templates**

`camp/templates/emissions/home.html`:

```django
{% extends 'emissions/base.html' %}
{% load emissions_explorer %}

{% block explorer-lede %}
<p class="is-size-5">Air pollution reported by permitted facilities, from power plants and glass factories to dairies and gas stations, in the California Air Resources Board's facility inventory.</p>
{% endblock %}

{% block breadcrumbs %}<span></span>{% endblock %}

{% block explorer-content %}
<div class="columns is-multiline has-text-centered">
    <div class="column"><p class="heading">Facilities in {{ year }}</p><p class="title">{{ totals.facilities }}</p></div>
    <div class="column"><p class="heading">{{ pollutant.name }}</p><p class="title">{{ total|amount:pollutant }} <span class="is-size-5">{{ pollutant.unit }}/yr</span></p></div>
    {% if top_sectors %}
    <div class="column"><p class="heading">Largest sector</p><p class="title is-4"><a href="{% url 'emissions:sector-detail' top_sectors.0.sector %}{{ scope_qs }}">{{ top_sectors.0.label }}</a></p></div>
    {% endif %}
</div>

{% if context_bar %}{% include 'emissions/includes/context-bar.html' %}{% endif %}

<h2 class="title is-4">Top 10 facilities</h2>
{% include 'emissions/includes/facility-table.html' with rows=top_rows sortable=False %}
<p class="mb-5"><a href="{% url 'emissions:facility-list' %}{{ scope_qs }}">All facilities →</a></p>

<div class="columns">
    <div class="column">
        <h2 class="title is-4">Top sectors</h2>
        {% include 'emissions/includes/sector-rows.html' with rows=top_sectors %}
        <p><a href="{% url 'emissions:sector-list' %}{{ scope_qs }}">All sectors →</a></p>
    </div>
    <div class="column">
        {% emissions_trend_chart by_year pollutant year %}
    </div>
</div>

<form method="get" action="{% url 'emissions:facility-list' %}" class="mt-5">
    {% for key, value in scope_params.items %}<input type="hidden" name="{{ key }}" value="{{ value }}">{% endfor %}
    <label class="label" for="facility-search">Find a facility</label>
    <div class="field has-addons">
        <div class="control is-expanded"><input class="input" type="search" id="facility-search" name="q" placeholder="Facility name"></div>
        <div class="control"><button class="button is-primary" type="submit">Search</button></div>
    </div>
</form>
{% endblock %}
```

`camp/templates/emissions/facility-list.html`:

```django
{% extends 'emissions/base.html' %}
{% load pesticides_explorer %}

{% block title %}Facilities | {{ block.super }}{% endblock %}
{% block breadcrumb-list %}<li class="is-active"><a aria-current="page">Facilities</a></li>{% endblock %}

{% block explorer-content %}
<form method="get" class="columns is-multiline is-variable is-2 mb-3">
    {% for key, value in scope_params.items %}<input type="hidden" name="{{ key }}" value="{{ value }}">{% endfor %}
    <input type="hidden" name="sort" value="{{ sort }}">
    <div class="column is-4"><input class="input" type="search" id="facility-q" name="q" value="{{ filters.q|default:'' }}" placeholder="Facility name"></div>
    <div class="column is-3"><div class="select is-fullwidth"><select name="sector" aria-label="Sector">
        <option value="">All sectors</option>
        {% for value, label in sector_options %}<option value="{{ value }}"{% if filters.sector == value %} selected{% endif %}>{{ label }}</option>{% endfor %}
    </select></div></div>
    {% if district_options|length > 1 %}
    <div class="column is-3"><div class="select is-fullwidth"><select name="district" aria-label="Air district">
        <option value="">All air districts</option>
        {% for district in district_options %}<option value="{{ district.external_id }}"{% if filters.district == district.external_id %} selected{% endif %}>{{ district.name }}</option>{% endfor %}
    </select></div></div>
    {% endif %}
    <div class="column is-2"><button class="button is-fullwidth" type="submit">Filter</button></div>
</form>

{% include 'emissions/includes/facility-table.html' with sortable=True %}
{% include 'pesticides/includes/pagination.html' %}
<p class="mt-3"><a href="{% qs_replace format='csv' page=None %}" hx-boost="false" download>Download these facilities (CSV)</a></p>
{% endblock %}
```

`camp/templates/emissions/facility-detail.html`:

```django
{% extends 'emissions/base.html' %}
{% load emissions_explorer pesticides_explorer %}

{% block title %}{{ facility.name|title }} | {{ block.super }}{% endblock %}
{% block breadcrumb-list %}
<li><a href="{% url 'emissions:facility-list' %}{{ scope_qs }}">Facilities</a></li>
<li class="is-active"><a aria-current="page">{{ facility.name }}</a></li>
{% endblock %}

{% block explorer-content %}
<div class="content">
    <h2 class="title is-3">{{ facility.name }}</h2>
    <p>{{ facility.address.street|title }}, {% if facility.city %}{{ facility.city.name }}{% else %}{{ facility.address.city|title }}{% endif %} · {{ facility.county.name }}</p>
    <p>
        <a href="{% url 'emissions:sector-detail' facility.sector %}{{ scope_qs }}">{{ facility.get_sector_display }}</a>
        {% if facility.sic_code %}{% sic_title facility.sic_code as sic_label %} · SIC {{ facility.sic_code }}{% if sic_label %}: {{ sic_label }}{% endif %}{% endif %}
        {% if facility.is_minor_source %} · <a href="{% url 'emissions:about' %}#minor-sources">Minor source</a>{% endif %}
    </p>
    <p>
        Regulated by {% if district.metadata.carb_url %}<a href="{{ district.metadata.carb_url }}">{{ district.name }}</a>{% else %}{{ district.name }}{% endif %}
        {% if district.metadata.phone %} · {{ district.metadata.phone }}{% endif %}
        {% if district.metadata.complaints_url %} · <a href="{{ district.metadata.complaints_url }}">Report an air pollution problem</a>{% endif %}
    </p>
</div>

{% if shown_year != year %}
<div class="notification is-light">This facility has no emissions reported for {{ year }}; showing {{ shown_year }}.</div>
{% endif %}

<h3 class="title is-4">Emissions in {{ shown_year }}</h3>
<div class="table-container">
<table class="table is-fullwidth is-narrow">
    <thead><tr><th>Pollutant</th><th class="has-text-right">Tons/yr</th><th>Rank in {{ facility.county.name|cut:" County" }} County</th><th>Rank in sector</th><th>Share of the county's facility total</th></tr></thead>
    <tbody>
        {% for row in ranks %}
        <tr>
            <td><a href="{% qs_replace pollutant=row.pollutant.key toxics=None %}">{{ row.pollutant.label }}</a>{% if row.pollutant.label != row.pollutant.name %} <span class="has-text-grey is-size-7">{{ row.pollutant.name }}</span>{% endif %}</td>
            <td class="has-text-right">{{ row.value|amount:row.pollutant }}</td>
            <td>{% if row.county_rank %}#{{ row.county_rank }} of {{ row.county_count }}{% else %}—{% endif %}</td>
            <td>{% if row.sector_rank %}#{{ row.sector_rank }} of {{ row.sector_count }}{% else %}—{% endif %}</td>
            <td>{{ row.county_share|percent }}</td>
        </tr>
        {% endfor %}
    </tbody>
</table>
</div>

{% if not pollutant.toxic %}{% emissions_trend_chart trend pollutant shown_year %}{% endif %}

{% if changes %}
<div class="notification is-warning is-light">
    <p>Large year-to-year changes can reflect changes in how emissions are estimated, not only real changes in what the facility emitted:</p>
    <ul>{% for change in changes %}<li>{{ change.pollutant.label }}: {{ change.pct|signed_pct }} from {{ change.previous_year }} to {{ change.year }}</li>{% endfor %}</ul>
</div>
{% endif %}

{% if toxics_rows %}
<h3 class="title is-4">Toxic air contaminants in {{ shown_year }}</h3>
<div class="table-container">
<table class="table is-fullwidth is-narrow">
    <thead><tr><th>Contaminant</th><th class="has-text-right">Lbs/yr</th><th class="has-text-right">Year before</th></tr></thead>
    <tbody>
        {% for row in toxics_rows %}
        <tr>
            <td>{{ row.pollutant.name }}</td>
            <td class="has-text-right">{{ row.value|floatformat:"-2" }}</td>
            <td class="has-text-right">{% if row.previous is not None %}{{ row.previous|floatformat:"-2" }}{% else %}—{% endif %}</td>
        </tr>
        {% endfor %}
    </tbody>
</table>
</div>
{% endif %}

<p class="is-size-7 has-text-grey">Source: California Air Resources Board facility emissions inventory (CEIDARS). <a href="{% url 'emissions:about' %}">About this data</a>.</p>
{% endblock %}
```

`camp/templates/emissions/sector-list.html`:

```django
{% extends 'emissions/base.html' %}

{% block title %}Sectors | {{ block.super }}{% endblock %}
{% block breadcrumb-list %}<li class="is-active"><a aria-current="page">Sectors</a></li>{% endblock %}

{% block explorer-content %}
<p class="mb-4">Facilities grouped by industry, from their Standard Industrial Classification (SIC) codes. {{ pollutant.name }}, {{ year }}.</p>
{% include 'emissions/includes/sector-rows.html' with show_trend=True show_description=True %}
{% endblock %}
```

`camp/templates/emissions/sector-detail.html`:

```django
{% extends 'emissions/base.html' %}
{% load emissions_explorer pesticides_explorer %}

{% block title %}{{ sector.label }} | {{ block.super }}{% endblock %}
{% block breadcrumb-list %}
<li><a href="{% url 'emissions:sector-list' %}{{ scope_qs }}">Sectors</a></li>
<li class="is-active"><a aria-current="page">{{ sector.label }}</a></li>
{% endblock %}

{% block explorer-content %}
<div class="content">
    <h2 class="title is-3">{{ sector.label }}</h2>
    <p>{% sector_description sector %}</p>
</div>

{% if summary %}
<div class="columns has-text-centered">
    <div class="column"><p class="heading">Facilities</p><p class="title">{{ summary.facilities }}</p></div>
    <div class="column"><p class="heading">{{ pollutant.name }}, {{ year }}</p><p class="title">{{ summary.value|amount:pollutant }} <span class="is-size-5">{{ pollutant.unit }}/yr</span></p></div>
    <div class="column"><p class="heading">Share of all facilities</p><p class="title">{{ summary.share|percent }}</p></div>
</div>
{% else %}
<p class="notification is-light">No facilities in this sector reported {{ pollutant.label }} in {{ year }}.</p>
{% endif %}

<div class="columns">
    <div class="column">{% emissions_trend_chart trend pollutant year %}</div>
    <div class="column">
        <h3 class="title is-5">By county</h3>
        <table class="table is-fullwidth is-narrow">
            <thead><tr><th>County</th><th class="has-text-right">Facilities</th><th class="has-text-right">{{ pollutant.unit|capfirst }}/yr</th><th>Share</th></tr></thead>
            <tbody>
                {% for row in counties %}
                <tr><td><a href="{% qs_replace county=row.county.slug %}">{{ row.county.name|cut:" County" }}</a></td><td class="has-text-right">{{ row.facilities }}</td><td class="has-text-right">{{ row.value|amount:pollutant }}</td><td>{{ row.share|percent }}</td></tr>
                {% endfor %}
            </tbody>
        </table>
    </div>
</div>

<h3 class="title is-4">Facilities</h3>
{% include 'emissions/includes/facility-table.html' with sortable=False %}
{% if facility_count > rows|length %}
<p><a href="{% url 'emissions:facility-list' %}{{ scope_qs }}{% if scope_qs %}&amp;{% else %}?{% endif %}sector={{ sector.value }}">All {{ facility_count }} facilities in this sector →</a></p>
{% endif %}
{% endblock %}
```

`camp/templates/emissions/about.html`:

```django
{% extends 'emissions/base.html' %}

{% block title %}About the data | {{ block.super }}{% endblock %}
{% block breadcrumb-list %}<li class="is-active"><a aria-current="page">About</a></li>{% endblock %}

{% block explorer-content %}
<div class="content">
<h2 id="coverage">What this covers</h2>
<p>The Facility Emissions Explorer shows air pollution reported by <strong>permitted stationary sources</strong> in the San Joaquin Valley's eight counties: power plants, glass and cement plants, oil fields, food processors, dairies with permits, landfills, hospitals, gas stations and thousands more. The data is the California Air Resources Board's facility inventory (CEIDARS), which the air districts report to CARB every year.</p>
<p>It does <strong>not</strong> cover cars and trucks, farm equipment, trains, most farming and dust, consumer products, wildfires, or facilities too small to need a permit. Those are most of the valley's air pollution; see <a href="#carb-estimates">CARB's estimates of all sources</a>.</p>

<h2 id="districts">Two air districts</h2>
<p>Seven of the eight counties are entirely within the San Joaquin Valley Air Pollution Control District. Kern County is split: its desert and mountain east is the Eastern Kern Air Pollution Control District, which regulates Kern's largest cement plants, US Borax at Boron and Edwards Air Force Base. Each facility's page names the district that regulates it and how to report a problem to them.</p>

<h2 id="carb-estimates">CARB's estimates of all sources</h2>
<p>For context, pages compare permitted facilities with CARB's estimate of all emissions in a county: stationary, areawide (farming, dust, consumer products, residential wood burning), mobile (vehicles and equipment) and natural sources. Those estimates come from CARB's CEPAM model, whose most recent inventory uses <strong>2017 as its base year</strong>; every other year is CARB's projection from it, not a new inventory. CARB publishes them in tons per day, which the explorer converts to tons per year.</p>

<h2 id="units">Pollutants and units</h2>
<ul>
    <li><strong>NOx</strong> (nitrogen oxides) and <strong>ROG</strong> (reactive organic gases) form ozone and fine particles.</li>
    <li><strong>Total PM</strong> is all particulate matter. CARB's facility inventory doesn't report PM2.5 by facility, so the explorer shows Total PM and PM10 instead.</li>
    <li><strong>SOx</strong> (sulfur oxides), <strong>CO</strong> (carbon monoxide) and <strong>TOG</strong> (total organic gases) round out the criteria pollutants.</li>
    <li>Criteria pollutants are in <strong>tons per year</strong>. The ten <strong>toxic air contaminants</strong> (benzene, formaldehyde, hexavalent chromium and others) are in <strong>pounds per year</strong>, because the amounts are small.</li>
</ul>

<h2 id="minor-sources">Minor sources</h2>
<p>Gas stations, dry cleaners, auto body shops and small print shops are permitted, but CARB leaves them out of its facility totals by default and counts them in its county-wide estimates instead. The explorer does the same; turn on <em>Include minor sources</em> to add them.</p>

<h2 id="years">Years and changes</h2>
<p>The explorer covers 2010 onward. The number of facilities grows over those years partly because reporting coverage grew. A large change from one year to the next can reflect a new way of estimating a facility's emissions, not only a real change in what it emitted; facility pages point these out.</p>

<h2 id="sources">Sources</h2>
<ul>
    <li><a href="https://ww2.arb.ca.gov/criteria-pollutant-emission-inventory-data">CARB facility emissions inventory (CEIDARS)</a></li>
    <li><a href="https://ww2.arb.ca.gov/applications/cepam2019v1-04-standard-emission-tool">CARB CEPAM 2019 emission projections</a></li>
    <li><a href="https://ww2.arb.ca.gov/california-air-districts">CARB air district directory</a> and <a href="https://gis.data.ca.gov/datasets/CaliforniaARB::california-air-district-boundaries/about">district boundaries</a></li>
</ul>
</div>
{% endblock %}
```

- [ ] **Step 8: Styles**

Create `assets/sass/sjvair/pages/emissions.sass`:

```sass
// Emissions explorer additions; the shared explorer chrome is in pesticides.sass (body.pesticides).
body.emissions
  .emissions-context-bar
    display: flex
    height: 1.25rem
    border-radius: 4px
    overflow: hidden
    margin: 0.75rem 0 0.5rem
  .segment, .swatch
    &.is-stationary
      background: #08519c
    &.is-areawide
      background: #6baed6
    &.is-mobile
      background: #9ecae1
    &.is-natural
      background: #deebf7
  .segment
    height: 100%
  .emissions-legend
    display: flex
    flex-wrap: wrap
    gap: 0.25rem 1rem
    font-size: 0.875rem
  .swatch
    display: inline-block
    width: 0.75rem
    height: 0.75rem
    margin-right: 0.3rem
    border-radius: 2px
    vertical-align: middle
  .share-bar
    background: #deebf7
    height: 0.5rem
    width: 6rem
    border-radius: 2px
    display: inline-block
    margin-right: 0.5rem
    vertical-align: middle
    span
      display: block
      height: 100%
      background: #3182bd
  .sparkline polyline
    fill: none
    stroke: #3182bd
    stroke-width: 1.5
  .facility-table tr.is-minor td
    color: #6b7280
```

In `assets/sass/style.sass`, after `@import "sjvair/pages/pesticides"` add `@import "sjvair/pages/emissions"`.

- [ ] **Step 9: Run the tests**

Run: `$TEST camp/apps/emissions camp/apps/pesticides/tests/test_views.py`
Expected: all PASS (the pesticides view tests confirm nothing shared broke).

- [ ] **Step 10: Look at it**

Compile styles and load each page against real data (after Task 2–4 imports have been run locally): `docker compose run --rm web invoke styles`, then run the worktree's server on port 8003 (`docker compose -f /home/derek/dev/ccac/sjvair.com/docker-compose.yml --project-directory /home/derek/dev/ccac/sjvair.com run --rm --name emissions-explorer-web8003 -p 8003:8000 -v /home/derek/dev/ccac/sjvair.com/.claude/worktrees/feature+ceidars-explorer:/app web python manage.py runserver 0:8000`) and open `/tools/emissions/`, `/tools/emissions/facilities/`, one facility page, `/tools/emissions/sectors/`, one sector page, `/tools/emissions/about/`. Check the scope dropdowns open (explorer.js), the trend chart draws (charts.js), and boosted navigation swaps the body without a full reload.

- [ ] **Step 11: Commit**

```bash
git add camp/apps/emissions/models.py camp/apps/emissions/templatetags camp/apps/emissions/views.py \
  camp/apps/emissions/urls.py camp/urls.py camp/templates/emissions assets/sass/sjvair/pages/emissions.sass \
  assets/sass/style.sass camp/apps/emissions/tests/test_views.py camp/apps/emissions/tests/test_templatetags.py
git commit -m "feat(emissions): Facility Emissions Explorer pages"
```

---
### Task 7: Facility map

**Files:**
- Create: `camp/api/v2/emissions/geojson.py`; modify `camp/api/v2/emissions/urls.py`, `camp/api/v2/emissions/tests.py`
- Modify: `camp/apps/emissions/views.py` (`facility_map_config`, `MapPage`, map config on facility + sector pages), `camp/apps/emissions/urls.py` (`map/`)
- Create: `camp/templates/emissions/map.html`, `camp/templates/emissions/includes/facility-map.html`
- Modify: `camp/templates/emissions/base.html` (map assets, Map tab), `facility-detail.html`, `sector-detail.html`
- Create: `assets/js/emissions/facility-map.js`, `assets/css/emissions/facility-map.css`
- Modify: `assets/js/pesticides/explorer.js` (one init line in the `htmx:load` hook)
- Create: `scripts/emissions_map_smoke.py`
- Test: `camp/apps/emissions/tests/test_views.py` (map cases)

**Interfaces:**
- Consumes: `stats.resolve_scope`, `stats.facility_table`, `stats.ranks`, `Scope.params()` (Task 5); `ScopeMixin` (Task 6); the pesticides county outline endpoint `api:v2:pesticides:county-list` (covered-county outlines as GeoJSON, cached a day); the vendored `maptiler-sdk/maptiler-sdk.{js,css}` from `invoke bundle`.
- Produces: API names `api:v2:emissions:geojson` (`facilities/geojson/`) and `api:v2:emissions:districts` (`districts/`); URL name `emissions:map`; `views.facility_map_config(scope, *, mode='full', highlight=None, sector=None) -> dict`; JS global `window.EmissionsFacilityMap = {init(root), instances()}`; the map container sets `data-loaded="1"` once facilities are drawn (the smoke test waits on it).

- [ ] **Step 1: Write the failing tests**

Append to `camp/api/v2/emissions/tests.py`:

```python
from django.contrib.gis.geos import MultiPolygon, Polygon
from django.core.cache import cache

from camp.apps.regions.models import Boundary, Region


class FacilityGeoJSONTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        cache.clear()

    def features(self, **params):
        response = self.client.get(reverse('api:v2:emissions:geojson'), params)
        assert response.status_code == 200
        return response.json()['features']

    def test_scope(self):
        features = self.features()
        assert [f['properties']['name'] for f in features] == ['TEST CEMENT', 'TEST PLANT']
        cement = features[0]
        assert cement['geometry'] == {'type': 'Point', 'coordinates': [-118.17, 35.05]}
        assert cement['properties']['value'] == 100.0
        assert cement['properties']['rank'] == 1
        assert cement['properties']['sector'] == 'Cement, concrete & minerals'
        assert cement['properties']['id'] == Facility.objects.get(name='TEST CEMENT').sqid

    def test_collection_properties(self):
        response = self.client.get(reverse('api:v2:emissions:geojson'), {'toxics': 1})
        body = response.json()
        assert body['properties'] == {'year': 2024, 'pollutant': 'benzene', 'label': 'Benzene', 'unit': 'lbs'}
        plant = [f for f in body['features'] if f['properties']['name'] == 'TEST PLANT'][0]
        assert plant['properties']['value'] == 2.0

    def test_filters(self):
        assert len(self.features(minor=1)) == 3
        assert [f['properties']['name'] for f in self.features(sector='glass')] == ['TEST PLANT']
        assert [f['properties']['name'] for f in self.features(county='fresno')] == ['TEST PLANT']

    def test_facilities_without_a_point_are_left_out(self):
        Facility.objects.filter(name='TEST PLANT').update(point=None)
        assert [f['properties']['name'] for f in self.features()] == ['TEST CEMENT']


class DistrictListTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def test_districts_with_facilities_and_boundaries(self):
        cache.clear()
        sju = Region.objects.get(pk=9001)
        sju.boundary = Boundary.objects.create(
            region=sju, version='test',
            geometry=MultiPolygon(Polygon.from_bbox((-121, 35, -118, 38)), srid=4326),
        )
        sju.save(update_fields=['boundary'])
        response = self.client.get(reverse('api:v2:emissions:districts'))
        features = response.json()['features']
        assert [f['properties']['code'] for f in features] == ['SJU']
        assert features[0]['properties']['name'] == 'San Joaquin Valley APCD'
        assert features[0]['geometry']['type'] in ('Polygon', 'MultiPolygon')
```

Append to `camp/apps/emissions/tests/test_views.py`:

```python
from urllib.parse import parse_qs

from camp.apps.emissions import stats, views


class MapTests(ViewTestCase):
    def test_map_page(self):
        content = self.get('map', params={'toxics': 1, 'sector': 'glass'}).content.decode()
        assert 'class="facility-map"' in content
        assert 'data-mode="full"' in content
        assert '/api/2.0/emissions/facilities/geojson/' in content
        assert 'value="glass" selected' in content

    def test_map_config(self):
        scope = stats.resolve_scope({'county': 'fresno', 'toxics': '1'})
        config = views.facility_map_config(scope, sector='glass')
        assert parse_qs(config['query']) == {'county': ['fresno'], 'toxics': ['1'], 'sector': ['glass']}
        assert config['unit'] == 'lbs'
        assert config['facility_url'].endswith('/facilities/{id}/')
        assert config['highlight'] == '' and config['center'] == ''

    def test_facility_page_has_a_compact_highlighted_map(self):
        content = self.client.get(self.plant.get_absolute_url()).content.decode()
        assert 'data-mode="compact"' in content
        assert f'data-highlight="{self.plant.sqid}"' in content
        assert 'data-center="36.737,-119.787"' in content

    def test_sector_page_map_is_filtered_to_the_sector(self):
        content = self.get('sector-detail', 'glass').content.decode()
        assert 'data-mode="compact"' in content
        assert 'sector=glass' in content

    def test_map_tab(self):
        assert reverse('emissions:map') in self.get('home').content.decode()
```

Run: `$TEST camp/api/v2/emissions/tests.py camp/apps/emissions/tests/test_views.py`
Expected: FAIL/ERROR (`NoReverseMatch` for `geojson`, `districts`, `map`).

- [ ] **Step 2: GeoJSON endpoints**

Create `camp/api/v2/emissions/geojson.py`:

```python
import json

from resticus import generics

from camp.apps.emissions import stats
from camp.apps.emissions.models import Facility
from camp.apps.regions.models import Region
from camp.utils.views import CachedEndpointMixin


class FacilityGeoJSONBase(generics.Endpoint):
    # get() lives on this un-cached base so CachedEndpointMixin.get() on the
    # subclass is the one dispatched to (the pesticides endpoints' pattern).
    def get(self, request):
        scope = stats.resolve_scope(request.GET)
        sector = request.GET.get('sector')
        sector = sector if sector in Facility.Sector.values else None
        rank_map = stats.ranks(scope)
        features = []
        for record in stats.facility_table(scope, sector=sector).filter(facility__point__isnull=False):
            facility = record.facility
            features.append({
                'type': 'Feature',
                'id': facility.sqid,
                'geometry': {
                    'type': 'Point',
                    'coordinates': [round(facility.point.x, 5), round(facility.point.y, 5)],
                },
                'properties': {
                    'id': facility.sqid,
                    'name': facility.name,
                    'sector': facility.get_sector_display(),
                    'value': scope.pollutant.display(record.value),
                    'rank': rank_map.get(record.facility_id),
                },
            })
        return {
            'type': 'FeatureCollection',
            'properties': {
                'year': scope.year,
                'pollutant': scope.pollutant.key,
                'label': scope.pollutant.label,
                'unit': scope.pollutant.unit,
            },
            'features': features,
        }


class FacilityGeoJSON(CachedEndpointMixin, FacilityGeoJSONBase):
    """
    Facilities in scope as GeoJSON points, for the explorer map. Parameters:
    year, county (slug), pollutant, toxics=1, minor=1, sector. `value` is in
    the pollutant's unit (tons/yr, or lbs/yr for toxics).
    """
    cache_timeout = 60 * 60
    cache_key_version = 1


class DistrictListBase(generics.Endpoint):
    def get(self, request):
        districts = (
            Region.objects.filter(type=Region.Type.AIR_DISTRICT, district_facilities__isnull=False)
            .distinct().select_related('boundary').order_by('name')
        )
        features = []
        for district in districts:
            if district.boundary is None:
                continue
            geometry = district.boundary.geometry.simplify(0.002, preserve_topology=True)
            features.append({
                'type': 'Feature',
                'id': district.sqid,
                'geometry': json.loads(geometry.geojson),
                'properties': {'id': district.sqid, 'name': district.name, 'code': district.external_id},
            })
        return {'type': 'FeatureCollection', 'features': features}


class DistrictList(CachedEndpointMixin, DistrictListBase):
    """Outlines of the air districts that regulate imported facilities, as GeoJSON, simplified for display."""
    cache_timeout = 60 * 60 * 24
    cache_key_version = 1
```

In `camp/api/v2/emissions/urls.py`, add **before** the `<str:facility_id>/` pattern:

```python
    path('facilities/geojson/', geojson.FacilityGeoJSON.as_view(), name='geojson'),
    path('districts/', geojson.DistrictList.as_view(), name='districts'),
```

(with `from . import endpoints, geojson`).

- [ ] **Step 3: Map config and views**

In `camp/apps/emissions/views.py` add imports `from urllib.parse import urlencode`, `from django.conf import settings`, `from django.urls import reverse`, and:

```python
MAP_STYLE = 'dataviz'


def facility_map_config(scope, *, mode='full', highlight=None, sector=None):
    """The data-* attributes of a `.facility-map` container (see assets/js/emissions/facility-map.js)."""
    params = scope.params()
    if sector:
        params['sector'] = sector
    point = highlight.point if highlight is not None else None
    return {
        'mode': mode,
        'geojson_url': reverse('api:v2:emissions:geojson'),
        'districts_url': reverse('api:v2:emissions:districts'),
        # The covered counties' outlines; the pesticides endpoint serves them for every explorer.
        'counties_url': reverse('api:v2:pesticides:county-list'),
        'query': urlencode(params),
        # The bare-sqid route redirects to the slugged page, so the JS needs no slug.
        'facility_url': reverse('emissions:facility-redirect', args=['__id__']).replace('__id__', '{id}'),
        'maptiler_key': settings.MAPTILER_API_KEY,
        'style': MAP_STYLE,
        'highlight': highlight.sqid if highlight is not None else '',
        'center': f'{point.y},{point.x}' if point is not None else '',
        'zoom': 11 if point is not None else '',
        'label': scope.pollutant.label,
        'unit': scope.pollutant.unit,
        'sector': sector or '',
    }


class MapPage(ScopeMixin, vanilla.TemplateView):
    template_name = 'emissions/map.html'
    section = 'map'

    def get_context_data(self, **kwargs):
        sector = self.request.GET.get('sector')
        sector = sector if sector in Facility.Sector.values else None
        return super().get_context_data(
            map_config=facility_map_config(self.get_scope(), sector=sector),
            sector_options=Facility.Sector.choices,
            **kwargs,
        )
```

In `FacilityDetail.get_context_data` add `map_config=facility_map_config(scope, mode='compact', highlight=facility),`; in `SectorDetail.get_context_data` add `map_config=facility_map_config(scope, mode='compact', sector=self.sector),`.

In `camp/apps/emissions/urls.py` add `path('map/', views.MapPage.as_view(), name='map'),` after `about/`.

- [ ] **Step 4: Templates**

`camp/templates/emissions/includes/facility-map.html`:

```django
<div class="facility-map-wrap{% if map_config.mode == 'compact' %} is-compact{% endif %}">
    <div class="facility-map"
         data-mode="{{ map_config.mode }}"
         data-geojson-url="{{ map_config.geojson_url }}"
         data-districts-url="{{ map_config.districts_url }}"
         data-counties-url="{{ map_config.counties_url }}"
         data-query="{{ map_config.query }}"
         data-facility-url="{{ map_config.facility_url }}"
         data-maptiler-key="{{ map_config.maptiler_key }}"
         data-style="{{ map_config.style }}"
         data-highlight="{{ map_config.highlight }}"
         data-center="{{ map_config.center }}"
         data-zoom="{{ map_config.zoom }}"
         data-label="{{ map_config.label }}"
         data-unit="{{ map_config.unit }}"></div>
    {% if map_config.mode == 'full' %}
    {# Shown by the script once the map is up; the sector filter narrows the map without a page swap. #}
    <form class="facility-map-toolbar" hidden>
        <div class="select is-small">
            <select name="sector" aria-label="Sector">
                <option value="">All sectors</option>
                {% for value, label in sector_options %}<option value="{{ value }}"{% if map_config.sector == value %} selected{% endif %}>{{ label }}</option>{% endfor %}
            </select>
        </div>
        <button type="button" class="button is-small" data-map-locate title="Show my location" aria-label="Show my location"><span class="fa-regular fa-location-crosshairs" aria-hidden="true"></span></button>
        <button type="button" class="button is-small" data-map-expand title="Expand the map" aria-label="Expand the map" aria-pressed="false"><span class="fa-regular fa-expand" aria-hidden="true"></span></button>
    </form>
    {% endif %}
    <div class="facility-map-legend" hidden></div>
</div>
```

`camp/templates/emissions/map.html`:

```django
{% extends 'emissions/base.html' %}

{% block title %}Map | {{ block.super }}{% endblock %}
{% block breadcrumb-list %}<li class="is-active"><a aria-current="page">Map</a></li>{% endblock %}

{% block explorer-content %}
{% include 'emissions/includes/facility-map.html' %}
<p class="is-size-7 mt-2">Each circle is a permitted facility; its area shows the facility's {{ pollutant.name|lower }} in {{ year }} and hollow grey circles reported none. Dashed purple lines are air district boundaries. <a href="{% url 'emissions:facility-list' %}{{ scope_qs }}">See these facilities as a table</a>.</p>
<noscript><p>The map needs JavaScript. <a href="{% url 'emissions:facility-list' %}{{ scope_qs }}">Browse the facility table instead</a>.</p></noscript>
{% endblock %}
```

In `camp/templates/emissions/base.html`:
- replace `{% block extra-head %}{% endblock %}` with
  ```django
  {% block extra-head %}
  <link rel="stylesheet" href="{% static 'maptiler-sdk/maptiler-sdk.css' %}">
  <link rel="stylesheet" href="{% static 'css/emissions/facility-map.css' %}">
  {% endblock %}
  ```
- in `{% block javascripts %}`, before the `explorer.js` script, add
  ```django
  <script src="{% static 'maptiler-sdk/maptiler-sdk.js' %}"></script>
  <script src="{% static 'js/emissions/facility-map.js' %}"></script>
  ```
- replace `{% block explorer-tabs-start %}{% endblock %}` with
  ```django
  {% block explorer-tabs-start %}
  <li class="{% if section == 'map' %}is-active{% endif %}"><a href="{% url 'emissions:map' %}{{ scope_qs }}" title="Map"><span class="icon is-small"><span class="fa-duotone fa-fw fa-map explorer-icon is-map" aria-hidden="true"></span></span><span class="tab-label">Map</span></a></li>
  {% endblock %}
  ```

In `facility-detail.html`, directly after the closing `</div>` of the header `content` block, add `{% include 'emissions/includes/facility-map.html' %}`. In `sector-detail.html`, directly before `<h3 class="title is-4">Facilities</h3>`, add `{% include 'emissions/includes/facility-map.html' %}`.

- [ ] **Step 5: The map module**

Create `assets/js/emissions/facility-map.js`:

```js
/*
 * Facility map for the Facility Emissions Explorer, on the MapTiler SDK
 * (MapLibre GL).
 *
 * Turns each `.facility-map` container into a map of permitted facilities:
 * one circle per facility, its area scaled by the selected pollutant (square
 * root, so the largest emitter doesn't bury the rest) and its colour by
 * quantile class; facilities that reported none are small hollow grey rings.
 * County and air district outlines sit underneath, and everything sits below
 * the basemap's labels. Config comes entirely from the container's data-*
 * attributes (emissions/includes/facility-map.html, views.facility_map_config).
 *
 * Modes: `full` (the map page: sector filter, locate, expand, legend) and
 * `compact` (facility and sector pages: no toolbar; a facility page's own
 * facility is highlighted and the rest faded).
 *
 * htmx: explorer.js calls EmissionsFacilityMap.init(root) after every swap. A
 * swap that brings a new container adopts the live map in place instead of
 * building another, so a page load uses one MapTiler session.
 *
 * Plain ES2017, no framework; one global, window.EmissionsFacilityMap.
 */
(function () {
  'use strict';

  // ColorBrewer Blues, 6 classes: the pesticides map's default ramp.
  var RAMP = ['#deebf7', '#c6dbef', '#9ecae1', '#6baed6', '#3182bd', '#08519c'];
  var EMPTY_COLOR = '#8a94a3';
  var HIGHLIGHT_COLOR = '#d35400';
  var COUNTY_COLOR = '#1f2d3d';
  var DISTRICT_COLOR = '#6a3d9a';
  var MIN_RADIUS = 3;
  var MAX_RADIUS = 26;
  var STYLE_PATHS = { dataviz: ['DATAVIZ'], 'dataviz-light': ['DATAVIZ', 'LIGHT'], streets: ['STREETS'] };
  var EMPTY_COLLECTION = { type: 'FeatureCollection', features: [] };

  var liveMap = null;
  var webglSupport = null;

  function webglAvailable() {
    if (webglSupport === null) {
      try {
        var canvas = document.createElement('canvas');
        webglSupport = !!(window.WebGLRenderingContext && (canvas.getContext('webgl2') || canvas.getContext('webgl')));
      } catch (err) {
        webglSupport = false;
      }
    }
    return webglSupport;
  }

  function logError(message, err) {
    if (window.console && console.error) console.error('facility-map: ' + message, err);
  }

  function styleFor(id) {
    var path = STYLE_PATHS[id];
    var style = path ? maptilersdk.MapStyle : null;
    for (var i = 0; style && i < path.length; i++) style = style[path[i]];
    return style || id;
  }

  // "36.75,-119.80" -> [lng, lat]; null when blank or malformed.
  function parseCenter(value) {
    if (!value || !String(value).trim()) return null;
    var parts = String(value).split(',').map(Number);
    if (parts.length !== 2 || !isFinite(parts[0]) || !isFinite(parts[1])) return null;
    return [parts[1], parts[0]];
  }

  function escapeHtml(text) {
    return String(text == null ? '' : text).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  // The same rules as the `amount` template filter.
  function amount(value) {
    if (value === null || value === undefined) return '—';
    var size = Math.abs(value);
    if (size && size < 0.01) return '<0.01';
    var digits = size && size < 1 ? 2 : (size && size < 10 ? 1 : 0);
    return value.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits });
  }

  // Upper bounds of the quantile classes over the positive values (at most RAMP.length - 1).
  function quantileBreaks(values) {
    var sorted = values.filter(function (v) { return v > 0; }).sort(function (a, b) { return a - b; });
    var breaks = [];
    for (var i = 1; i < RAMP.length && sorted.length; i++) {
      var value = sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * i / RAMP.length))];
      if (!breaks.length || value > breaks[breaks.length - 1]) breaks.push(value);
    }
    return breaks;
  }

  // However many classes there are, spread them across the whole ramp.
  function classColor(index, breaks) {
    return RAMP[breaks.length ? Math.round(index * (RAMP.length - 1) / breaks.length) : RAMP.length - 1];
  }

  function colorFor(value, breaks) {
    var index = 0;
    while (index < breaks.length && value > breaks[index]) index++;
    return classColor(index, breaks);
  }

  function radiusFor(value, max) {
    return MIN_RADIUS + (MAX_RADIUS - MIN_RADIUS) * Math.sqrt(value / max);
  }

  // Precompute each circle so the layer's paint is plain `get`s.
  function prepare(collection) {
    var features = collection.features || [];
    var values = features.map(function (f) { return f.properties.value; });
    var positive = values.filter(function (v) { return v > 0; });
    var max = positive.length ? Math.max.apply(null, positive) : 0;
    var breaks = quantileBreaks(values);
    features.forEach(function (feature) {
      var p = feature.properties;
      var reported = p.value > 0 && max > 0;
      p._radius = reported ? radiusFor(p.value, max) : MIN_RADIUS;
      p._color = reported ? colorFor(p.value, breaks) : EMPTY_COLOR;
      p._empty = reported ? 0 : 1;
      p._sort = reported ? p.value : 0;
    });
    return { collection: collection, breaks: breaks, max: max };
  }

  function FacilityMap(el) {
    this.el = el;
    this.data = el.dataset;
    this.wrap = el.closest('.facility-map-wrap');
    this.popup = null;
    this.request = 0;
    this.fitted = false;
    this.legendData = null;
    this.init();
  }

  FacilityMap.prototype.init = function () {
    var self = this;
    maptilersdk.config.apiKey = this.data.maptilerKey || '';
    this.map = new maptilersdk.Map({
      container: this.el,
      style: styleFor(this.data.style || 'dataviz'),
      center: parseCenter(this.data.center) || [-119.80, 36.75],
      zoom: parseFloat(this.data.zoom) || 7,
      navigationControl: false,
      geolocateControl: false,
      terrainControl: false,
      // Off until the map is clicked, so it doesn't hijack page scrolling.
      scrollZoom: false,
      pitchWithRotate: false,
      dragRotate: false,
      touchPitch: false,
      attributionControl: { compact: 'auto' },
      logoPosition: 'bottom-right',
    });
    this.map.touchZoomRotate.disableRotation();
    this.map.keyboard.disableRotation();
    this.map.addControl(new maptilersdk.NavigationControl({ showCompass: false }), 'top-left');
    this.el.addEventListener('click', function () { self.map.scrollZoom.enable(); });
    this.el.addEventListener('mouseleave', function () { self.map.scrollZoom.disable(); });
    // For debugging from the console: document.querySelector('.facility-map').facilityMap
    this.el.facilityMap = this;
    this.bindToolbar();
    this.map.on('load', function () {
      self.addLayers();
      self.load();
    });
  };

  // The first symbol layer: our layers go under the basemap's labels.
  FacilityMap.prototype.labelLayer = function () {
    var layers = this.map.getStyle().layers || [];
    for (var i = 0; i < layers.length; i++) {
      if (layers[i].type === 'symbol') return layers[i].id;
    }
    return undefined;
  };

  FacilityMap.prototype.addLayers = function () {
    var self = this;
    var before = this.labelLayer();
    this.map.addSource('counties', { type: 'geojson', data: this.data.countiesUrl || EMPTY_COLLECTION });
    this.map.addSource('districts', { type: 'geojson', data: this.data.districtsUrl || EMPTY_COLLECTION });
    this.map.addSource('facilities', { type: 'geojson', data: EMPTY_COLLECTION });
    this.map.addLayer({
      id: 'counties', type: 'line', source: 'counties',
      paint: { 'line-color': COUNTY_COLOR, 'line-width': 1, 'line-opacity': 0.5 },
    }, before);
    this.map.addLayer({
      id: 'districts', type: 'line', source: 'districts',
      paint: { 'line-color': DISTRICT_COLOR, 'line-width': 2, 'line-dasharray': [3, 2] },
    }, before);
    this.map.addLayer({
      id: 'facilities', type: 'circle', source: 'facilities',
      // Larger values draw on top.
      layout: { 'circle-sort-key': ['get', '_sort'] },
      paint: { 'circle-radius': ['get', '_radius'], 'circle-color': ['get', '_color'] },
    }, before);
    this.applyHighlight();
    this.map.on('click', 'facilities', function (evt) { self.openPopup(evt.features[0], evt.lngLat); });
    this.map.on('mouseenter', 'facilities', function () { self.map.getCanvas().style.cursor = 'pointer'; });
    this.map.on('mouseleave', 'facilities', function () { self.map.getCanvas().style.cursor = ''; });
  };

  // Hollow rings for "none reported"; with a highlighted facility (a facility
  // page), it gets an orange ring and everything else fades.
  FacilityMap.prototype.applyHighlight = function () {
    var id = this.data.highlight || '';
    var isHighlight = ['==', ['get', 'id'], id];
    var isEmpty = ['==', ['get', '_empty'], 1];
    this.map.setPaintProperty('facilities', 'circle-opacity',
      ['case', isEmpty, 0, id ? ['case', isHighlight, 0.95, 0.35] : 0.85]);
    this.map.setPaintProperty('facilities', 'circle-stroke-color',
      ['case', isHighlight, HIGHLIGHT_COLOR, isEmpty, EMPTY_COLOR, '#ffffff']);
    this.map.setPaintProperty('facilities', 'circle-stroke-width',
      ['case', isHighlight, 3, isEmpty, 1.25, 0.75]);
  };

  FacilityMap.prototype.url = function () {
    var query = this.data.query || '';
    return this.data.geojsonUrl + (query ? '?' + query : '');
  };

  FacilityMap.prototype.load = function () {
    var self = this;
    var ticket = ++this.request;
    this.el.dataset.loaded = '';
    fetch(this.url(), { credentials: 'same-origin' })
      .then(function (response) {
        if (!response.ok) throw new Error('HTTP ' + response.status);
        return response.json();
      })
      .then(function (collection) {
        // A newer request (a sector change, a swap) has superseded this one.
        if (ticket !== self.request) return;
        self.show(collection);
      })
      .catch(function (err) { logError('failed to load facilities', err); });
  };

  FacilityMap.prototype.show = function (collection) {
    var prepared = prepare(collection);
    this.legendData = prepared;
    this.map.getSource('facilities').setData(prepared.collection);
    this.applyHighlight();
    this.updateLegend();
    if (!this.fitted) {
      this.fit(prepared.collection);
      this.fitted = true;
    }
    this.el.dataset.loaded = '1';
  };

  // Frame the facilities, unless the page framed the map itself (a facility page's centre).
  FacilityMap.prototype.fit = function (collection) {
    if (parseCenter(this.data.center)) return;
    var features = collection.features || [];
    if (!features.length) return;
    var bounds = new maptilersdk.LngLatBounds();
    features.forEach(function (f) { bounds.extend(f.geometry.coordinates); });
    this.map.fitBounds(bounds, { padding: 40, maxZoom: 12, duration: 0 });
  };

  FacilityMap.prototype.facilityUrl = function (id) {
    var url = (this.data.facilityUrl || '').replace('{id}', encodeURIComponent(id));
    return url + (this.data.query ? '?' + this.data.query : '');
  };

  FacilityMap.prototype.openPopup = function (feature, lngLat) {
    var p = feature.properties;
    var value = p._empty ? 'none reported' : amount(p.value) + ' ' + escapeHtml(this.data.unit) + '/yr';
    var html = '<div class="facility-popup">' +
      '<p class="facility-popup-name"><a href="' + escapeHtml(this.facilityUrl(p.id)) + '">' + escapeHtml(p.name) + '</a></p>' +
      '<p>' + escapeHtml(p.sector) + '</p>' +
      '<p>' + escapeHtml(this.data.label) + ': <strong>' + value + '</strong>' + (p.rank ? ' · #' + p.rank : '') + '</p>' +
      '</div>';
    if (this.popup) this.popup.remove();
    this.popup = new maptilersdk.Popup({ maxWidth: '280px' }).setLngLat(lngLat).setHTML(html).addTo(this.map);
  };

  FacilityMap.prototype.updateLegend = function () {
    var legend = this.wrap && this.wrap.querySelector('.facility-map-legend');
    if (!legend || !this.legendData) return;
    var max = this.legendData.max;
    var breaks = this.legendData.breaks;
    var label = escapeHtml(this.data.label) + ' (' + escapeHtml(this.data.unit) + '/yr)';
    if (!max) {
      legend.innerHTML = '<p>No facilities here reported ' + escapeHtml(this.data.label) + '.</p>';
      legend.hidden = false;
      return;
    }
    var sizes = [max, max / 10, max / 100].map(function (value) {
      var r = radiusFor(value, max);
      return '<span class="legend-size"><svg width="' + (2 * MAX_RADIUS + 2) + '" height="' + (2 * r + 2) + '">' +
        '<circle cx="' + (MAX_RADIUS + 1) + '" cy="' + (r + 1) + '" r="' + r + '"/></svg>' + amount(value) + '</span>';
    }).join('');
    var bins = '';
    for (var i = 0; i <= breaks.length; i++) {
      var low = i ? breaks[i - 1] : 0;
      var high = i < breaks.length ? breaks[i] : max;
      bins += '<span class="legend-bin"><span class="legend-swatch" style="background:' + classColor(i, breaks) + '"></span>' +
        amount(low) + '–' + amount(high) + '</span>';
    }
    legend.innerHTML = '<p class="legend-title">' + label + '</p>' +
      '<div class="legend-sizes">' + sizes + '</div>' +
      '<div class="legend-bins">' + bins + '</div>' +
      '<p class="legend-empty"><span class="legend-ring"></span>None reported</p>';
    legend.hidden = false;
  };

  FacilityMap.prototype.bindToolbar = function () {
    var self = this;
    var toolbar = this.wrap && this.wrap.querySelector('.facility-map-toolbar');
    if (!toolbar || toolbar.dataset.bound) return;
    toolbar.dataset.bound = '1';
    toolbar.hidden = false;
    toolbar.addEventListener('submit', function (evt) { evt.preventDefault(); });
    toolbar.addEventListener('change', function () { self.setSector(toolbar.elements.sector.value); });
    var locate = toolbar.querySelector('[data-map-locate]');
    if (locate) locate.addEventListener('click', function () { self.locate(); });
    var expand = toolbar.querySelector('[data-map-expand]');
    if (expand) expand.addEventListener('click', function () { self.toggleExpanded(expand); });
  };

  // The sector filter narrows the map without a page swap; the address bar
  // follows so the view can be shared.
  FacilityMap.prototype.setSector = function (sector) {
    var params = new URLSearchParams(this.data.query || '');
    var page = new URLSearchParams(window.location.search);
    if (sector) {
      params.set('sector', sector);
      page.set('sector', sector);
    } else {
      params.delete('sector');
      page.delete('sector');
    }
    this.data.query = params.toString();
    var search = page.toString();
    window.history.replaceState(window.history.state, '', window.location.pathname + (search ? '?' + search : ''));
    this.load();
  };

  FacilityMap.prototype.locate = function () {
    var self = this;
    if (!navigator.geolocation) return;
    navigator.geolocation.getCurrentPosition(function (position) {
      self.map.flyTo({ center: [position.coords.longitude, position.coords.latitude], zoom: 11 });
    }, function (err) { logError('location unavailable', err); });
  };

  FacilityMap.prototype.toggleExpanded = function (button) {
    var expanded = this.wrap.classList.toggle('is-expanded');
    document.documentElement.classList.toggle('facility-map-expanded', expanded);
    button.setAttribute('aria-pressed', expanded ? 'true' : 'false');
    this.map.resize();
  };

  // A boosted swap brought a new container: put the live map's element in
  // its place, take its config, and reload the facilities.
  FacilityMap.prototype.adopt = function (el) {
    document.documentElement.classList.remove('facility-map-expanded');
    el.parentNode.replaceChild(this.el, el);
    var keys = Object.keys(el.dataset);
    for (var i = 0; i < keys.length; i++) this.el.dataset[keys[i]] = el.dataset[keys[i]];
    this.el.dataset.rendered = '1';
    this.data = this.el.dataset;
    this.wrap = this.el.closest('.facility-map-wrap');
    if (this.popup) {
      this.popup.remove();
      this.popup = null;
    }
    this.bindToolbar();
    this.fitted = false;
    this.map.resize();
    var center = parseCenter(this.data.center);
    if (center) this.map.jumpTo({ center: center, zoom: parseFloat(this.data.zoom) || this.map.getZoom() });
    if (this.map.getSource('facilities')) this.load();
  };

  FacilityMap.prototype.destroy = function () {
    document.documentElement.classList.remove('facility-map-expanded');
    if (this.popup) this.popup.remove();
    this.map.remove();
  };

  function containersUnder(root) {
    var found = [];
    if (root.matches && root.matches('.facility-map')) found.push(root);
    var nested = root.querySelectorAll ? root.querySelectorAll('.facility-map') : [];
    for (var i = 0; i < nested.length; i++) found.push(nested[i]);
    return found;
  }

  // Idempotent: initialised containers carry data-rendered, so this is safe
  // to call on page load and after every htmx swap.
  function init(root) {
    if (typeof maptilersdk === 'undefined') return;
    var containers = containersUnder(root || document);
    // A swap to a page without a map releases the live one. Judged against
    // the whole document: htmx fires htmx:load per swapped element, and the
    // one for an out-of-band fragment must not take the map away.
    if (liveMap && !document.body.contains(liveMap.el) && !containersUnder(document).length) {
      liveMap.destroy();
      liveMap = null;
    }
    for (var i = 0; i < containers.length; i++) {
      var el = containers[i];
      if (el.dataset.rendered) continue;
      try {
        if (!webglAvailable()) {
          el.dataset.rendered = '1';
          el.classList.add('is-unavailable');
          el.innerHTML = '<p class="facility-map-note">This map needs WebGL, which this browser has turned off or doesn\'t support.</p>';
          continue;
        }
        if (liveMap && !document.body.contains(liveMap.el)) {
          liveMap.adopt(el);
          continue;
        }
        el.dataset.rendered = '1';
        liveMap = new FacilityMap(el);
      } catch (err) {
        logError('failed to initialize', err);
      }
    }
  }

  window.EmissionsFacilityMap = {
    init: init,
    instances: function () { return liveMap ? [liveMap] : []; },
  };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () { init(document); });
  } else {
    init(document);
  }
})();
```

Create `assets/css/emissions/facility-map.css`:

```css
/* Facility map (assets/js/emissions/facility-map.js). */
.facility-map-wrap { position: relative; margin-bottom: 1rem; }
.facility-map { height: 70vh; min-height: 420px; border-radius: 6px; overflow: hidden; }
.facility-map-wrap.is-compact .facility-map { height: 320px; min-height: 0; }
.facility-map.is-unavailable { display: flex; align-items: center; justify-content: center; background: #f5f5f5; }
.facility-map-wrap.is-expanded { position: fixed; inset: 0; z-index: 40; margin: 0; background: #fff; }
.facility-map-wrap.is-expanded .facility-map { height: 100%; border-radius: 0; }
html.facility-map-expanded { overflow: hidden; }
.facility-map-toolbar { position: absolute; top: 10px; left: 50px; z-index: 2; display: flex; gap: 0.4rem; }
.facility-map-legend {
  position: absolute; bottom: 30px; left: 10px; z-index: 2; max-width: 260px;
  padding: 0.5rem 0.75rem; border-radius: 4px; font-size: 0.75rem;
  background: rgba(255, 255, 255, 0.92); box-shadow: 0 1px 3px rgba(0, 0, 0, 0.2);
}
.facility-map-legend .legend-title { font-weight: 600; margin-bottom: 0.25rem; }
.legend-sizes { display: flex; align-items: flex-end; gap: 0.5rem; }
.legend-size { display: inline-flex; flex-direction: column; align-items: center; }
.legend-size circle { fill: none; stroke: #3182bd; stroke-width: 1.25; }
.legend-bins { display: flex; flex-direction: column; margin-top: 0.25rem; }
.legend-swatch { display: inline-block; width: 0.7rem; height: 0.7rem; margin-right: 0.3rem; border-radius: 50%; vertical-align: middle; }
.legend-ring { display: inline-block; width: 0.6rem; height: 0.6rem; margin-right: 0.3rem; border: 1.25px solid #8a94a3; border-radius: 50%; vertical-align: middle; }
.legend-empty { margin-top: 0.25rem; }
.facility-popup p { margin: 0 0 0.2rem; }
.facility-popup-name { font-weight: 600; }
@media (max-width: 768px) {
  .facility-map { height: 60vh; }
  .facility-map-legend { max-width: 180px; }
}
```

In `assets/js/pesticides/explorer.js`, inside the `htmx:load` handler after the `PesticidesSectionMap` line, add:

```js
    if (window.EmissionsFacilityMap) window.EmissionsFacilityMap.init(root);
```

- [ ] **Step 6: Smoke script**

Create `scripts/emissions_map_smoke.py`:

```python
"""
Headless smoke test for the Facility Emissions Explorer's map.

Loads the map page and a few compact-map pages in headless Chrome, waits for
the facilities to draw (`data-loaded="1"` on the container), checks features
were drawn, switches the map page's sector filter and waits for the redraw,
follows a boosted tab link and back to check the live map is adopted rather
than rebuilt, and fails on any console error. Dev-only; nothing here runs in
CI. Needs local data (import_air_districts, import_ceidars, import_cepam).

Setup (Chrome must be installed):
    python3 -m venv .venv && .venv/bin/pip install selenium
Usage:
    .venv/bin/python scripts/emissions_map_smoke.py --base http://localhost:8003
"""
import argparse
import sys
import time

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select

MAP_TIMEOUT = 40


def browser():
    opts = Options()
    opts.add_argument('--headless=new')
    opts.add_argument('--window-size=1400,1000')
    # Software WebGL: the SDK map needs a GL context and headless has no GPU.
    opts.add_argument('--enable-unsafe-swiftshader')
    opts.add_argument('--ignore-gpu-blocklist')
    opts.add_argument('--disable-application-cache')
    opts.set_capability('goog:loggingPrefs', {'browser': 'ALL'})
    return webdriver.Chrome(options=opts)


def wait_loaded(driver, timeout=MAP_TIMEOUT):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if driver.execute_script("var el = document.querySelector('.facility-map'); return !!el && el.dataset.loaded === '1';"):
            return True
        time.sleep(0.25)
    return False


def feature_count(driver):
    return driver.execute_script(
        "var m = window.EmissionsFacilityMap.instances()[0];"
        "return m ? m.map.querySourceFeatures('facilities').length : 0;"
    )


def console_errors(driver):
    return [entry['message'] for entry in driver.get_log('browser') if entry['level'] == 'SEVERE']


def check(results, name, passed, detail=''):
    results.append((name, passed, detail))
    print(f"{'PASS' if passed else 'FAIL'}  {name}  {detail}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', default='http://localhost:8003')
    args = parser.parse_args()
    results = []

    driver = browser()
    try:
        driver.get(args.base + '/tools/emissions/map/')
        check(results, 'map page loads facilities', wait_loaded(driver))
        check(results, 'map page draws features', feature_count(driver) > 0, f'{feature_count(driver)} features')
        instance = driver.execute_script('return window.EmissionsFacilityMap.instances()[0].map._mapId || 1;')

        select = Select(driver.find_element(By.CSS_SELECTOR, '.facility-map-toolbar select[name=sector]'))
        select.select_by_value('glass')
        time.sleep(0.5)
        check(results, 'sector filter redraws', wait_loaded(driver) and 'sector=glass' in driver.current_url, driver.current_url)

        driver.find_element(By.CSS_SELECTOR, '.explorer-scope-picker[data-scope=pollutant] .button').click()
        driver.find_element(By.CSS_SELECTOR, '.explorer-scope-picker[data-scope=pollutant] .dropdown-item:nth-child(2)').click()
        time.sleep(1)
        check(results, 'pollutant change (boosted swap) reloads', wait_loaded(driver))
        same = driver.execute_script('return window.EmissionsFacilityMap.instances().length === 1;')
        check(results, 'one live map after the swap', same, str(instance))

        driver.get(args.base + '/tools/emissions/facilities/')
        link = driver.find_element(By.CSS_SELECTOR, '.facility-table tbody a').get_attribute('href')
        driver.get(link)
        check(results, 'facility page compact map loads', wait_loaded(driver))

        driver.get(args.base + '/tools/emissions/sectors/power-plants/')
        check(results, 'sector page compact map loads', wait_loaded(driver))

        errors = console_errors(driver)
        check(results, 'no console errors', not errors, '; '.join(errors)[:300])
    finally:
        driver.quit()

    failed = [name for name, passed, _ in results if not passed]
    print(f'\n{len(results) - len(failed)}/{len(results)} checks passed')
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
```

- [ ] **Step 7: Run the tests**

Run: `$TEST camp/apps/emissions camp/api/v2/emissions camp/apps/pesticides/tests/test_views.py`
Expected: all PASS.

- [ ] **Step 8: Build assets and smoke-test**

`docker compose run --rm web invoke vendor bundle styles` (from the worktree: prefix as in `$TEST`, `web invoke ...`), start the server on port 8003 (Task 6 Step 10), hard-refresh (static JS is not cache-busted), then run `scripts/emissions_map_smoke.py --base http://localhost:8003`. Expected: every check PASS. Open `/tools/emissions/map/` yourself too: CalPortland (Mojave) should be the largest circle with NOx selected, the dashed district line should separate Eastern Kern, and hollow rings should appear with a toxic selected.

- [ ] **Step 9: Commit**

```bash
git add camp/api/v2/emissions/geojson.py camp/api/v2/emissions/urls.py camp/api/v2/emissions/tests.py \
  camp/apps/emissions/views.py camp/apps/emissions/urls.py camp/templates/emissions \
  assets/js/emissions/facility-map.js assets/css/emissions/facility-map.css assets/js/pesticides/explorer.js \
  scripts/emissions_map_smoke.py camp/apps/emissions/tests/test_views.py
git commit -m "feat(emissions): facility map with sized circles and district outlines"
```

---

### Task 8: Final verification and PR notes

**Files:**
- Create (scratchpad, not committed): the PR description draft

- [ ] **Step 1: Full suite**

Run: `$TEST` with no paths (the whole `camp` tree, as CI does).
Expected: all PASS. A failure elsewhere that mentions `relation ... does not exist` or a connection error is contention from another session's test run on the shared DB container; re-run before investigating.

- [ ] **Step 2: Migrations are settled**

Run: `... test python manage.py makemigrations regions emissions ceidars --check --dry-run`
Expected: `No changes detected`.

- [ ] **Step 3: Real-data pass**

Against the local dev DB (the web service, not the test DB): `migrate`, `import_air_districts`, `import_ceidars --year Y` for 2010–2024 (or at least 2023 and 2024), `assign_sectors` (prints `0 facilities updated` after a fresh import), `import_cepam --year 2010-2024`. Then check by hand on port 8003:
- Kern includes Eastern Kern: the Kern county scope's top NOx facility is CalPortland (Mojave), regulated by Eastern Kern APCD.
- The landing page's context bar appears for NOx and disappears for toxics.
- `other` is a small share of facilities (`Facility.objects.filter(sector='other').count()`); if a common SIC lands there, add it to `sectors.py` (and a test case) before finishing.

- [ ] **Step 4: Draft the PR description (do not open the PR)**

Write the draft to the session scratchpad with: summary; screenshots placeholder list for Derek; **deploy steps in order**: `migrate` (drops the `ceidars_*` tables, creates `emissions_*`, adds the `air_district` Region type) → `import_counties` if any county Region lacks `metadata.ca_county_code` → `import_air_districts` → `import_ceidars --year Y` for each year 2010–2024 → `import_cepam --year 2010-2024` → `invoke vendor bundle styles` → flush the cache → hard refresh (static JS isn't cache-busted); the API move (`/api/2.0/ceidars/` → `/api/2.0/emissions/`, nothing consumed it); the follow-up from the spec (recompute the Kern forecast zone from the SJU district). Report the draft's path to Derek; he decides when to push and open the PR.
