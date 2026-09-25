# Emissions by Area Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the Facility Emissions Explorer's "by area" features:
- an Areas view of the map (counties, ZIP areas or 2020 census tracts shaded by the emissions of the facilities inside them);
- region pages and a near-me page;
- an "Area" line on facility pages;
- ACS population.

**Architecture:**
- **Facility-to-region mapping.** Facilities are mapped to ZIP areas and tracts by the region their point falls in. The mapping is computed with one spatial query per level and cached a day, and never stored on the model.
- **Area totals and pages.** The map's area values and the region pages both sum `EmissionsRecord`s through that mapping. A new optional `Scope.area` narrows every existing `stats` aggregate to a region or radius.
- **Map shapes.** They come from the regions GeoJSON endpoint, simplified as a coverage so shared borders stay identical.

**Tech Stack:** Django/GeoDjango + PostGIS, django-resticus, vanilla views, htmx, MapTiler SDK on the map core (`window.SJVAirMaps`), Shapely 2.1 (`coverage_simplify`, GEOS 3.13 in the image), uPlot charts, Bulma, Selenium smoke scripts.

**Spec:** `docs/superpowers/specs/2026-09-24-emissions-areas-design.md` (read it before any task).

## Global Constraints

- **Where to work.** Worktree `/home/derek/dev/ccac/sjvair.com/.claude/worktrees/feature+ceidars-explorer`, branch `feature/ceidars-explorer` (`<worktree>` below).
  - Use absolute paths, and `git -C <worktree>` for every git command.
  - Never edit or commit in `/home/derek/dev/ccac/sjvair.com` or any other worktree. `feature+pesticides-explorer` belongs to another session.
  - After each commit, verify it with `git -C <worktree> log --oneline -1`.
- **Tests.**
  - Run them through the main compose, with a private test DB:
    `docker compose -f /home/derek/dev/ccac/sjvair.com/docker-compose.yml --project-directory /home/derek/dev/ccac/sjvair.com run --rm -T -e DATABASE_URL=postgis://sjvair:changeme@db:5432/sjvair_emissions -v <worktree>:/app test pytest <paths> -q -p no:cacheprovider --create-db`
    This is `$TEST <paths>` below. `fatal: not a git repository` in its output is harmless.
  - Style: `django.test.TestCase`, plain `assert`, `pytest.raises` for exceptions.
- **Dev server.** Derek's server on port 8003 serves this worktree; find it with `docker ps --filter publish=8003`.
  - Don't stop it. Run management commands in it with `docker exec <container> python manage.py …`.
  - Static files aren't cache-busted: after JS/CSS changes, rebuild with `docker compose … run --rm -v <worktree>:/app web invoke vendor bundle styles` (same compose prefix) and hard-refresh.
- **Smoke scripts.** Selenium lives in the venv `/home/derek/.claude/jobs/d44a9b36/tmp/venv`. Run `<venv>/bin/python <worktree>/scripts/emissions_map_smoke.py --base http://localhost:8003`.
- **JS.** Plain ES2017 IIFE, `'use strict'`, `var`, no bundler. The facility map is module `facility` on the map core. Check syntax with `node --check <file>`.
- **Commits.** Stage files explicitly (never `git add -A` or `.`). Local only, never push. No AI-attribution or Co-Authored-By trailer.
- **Levels.** `county`, `zipcode`, `tract` (the `Region.Type` values). Default level `zipcode`.
- **Measures.** `density` (per square mile, default), `total`, `per_resident`.
- **2020 tracts.** Everywhere in this work, tracts are the ones whose current boundary is version `'2020'`. The 183 retired 2010-only tracts stay in the database but never appear.
- **Membership.**
  - County: `Facility.county`.
  - ZIP and tract: the region containing `Facility.point`.
  - Region pages of other types (city, place, school district): point within the boundary.
  - Near-me: within the radius.
  - Facility data is never modified; no new model fields.
- **Values.**
  - Units are the pollutant's display unit (`Pollutant.display()`: tons/yr, lbs/yr for toxics).
  - Areas are square miles from the full-precision boundary in California Albers (EPSG 3310).
  - Population is `Region.metadata['population']`.
- **Region page types.** County, city, zipcode, place, school district, tract. No air districts.

**Refinements to the spec, made while planning:**
1. **Per-resident unit.** Per-resident values are per **1,000 residents** (`per_1k_residents`). Tons per resident are too small to read (0.0004).
2. **Region page charts.** The trend is the area's total by year, drawn with the existing trend chart (`emissions_trend_chart`). The by-sector breakdown uses the existing share-bar rows (`emissions/includes/sector-rows.html`). A trend stacked by sector would need a new chart type in `charts.js`; that's deferred.
3. **Tracts in search.** Tracts are not in the find-your-area search list, because their names are GEOIDs. Readers reach them from Areas popups and facility "Area" lines. Tract pages are titled with the tract's `metadata['namelsad']` ("Census Tract 26.01") and county.
4. **Short region URL.** `region/<sqid>/` redirects to the slugged URL, so map popups can link without knowing the slug (the facility pattern).
5. **Map on area pages.** It shows every facility in scope, framed on the area, with everything outside washed out (the pesticides place-page behaviour).

## Review Focus

- **A facility exactly on a shared ZIP/tract border.** It must count once, not twice and not zero. Covered by Task 4 (`region_index` takes one containing region).
- **A region with no population, or zero.** Per-resident is `None`: "—" in the popup, the area unshaded, never a division error. Covered by Task 4.
- **A near-me point outside every county, or with garbage/over-length params.** The page bounces to the find form, and never 500s. Covered by Task 6.
- **An Areas response too big to cache.** The request must still succeed (Task 1). The tract shapes must stay small enough to cache (measured in Task 2 and Task 9).
- **A year or pollutant change while in Areas (a boosted swap).** The scope-bar links were rendered before the reader switched view, so without help the next page reopens on Facilities. It must keep one live map, still in Areas at the same level and measure, and keep the sector. Covered by the htmx hook in Task 8 and its smoke check.

---

### Task 1: A failed cache write never fails the request

**Files:**
- Modify: `camp/utils/views.py` (`CachedEndpointMixin.get`, plus a module logger)
- Test: `camp/utils/tests/test_cached_endpoint.py`

**Interfaces:**
- Produces: `CachedEndpointMixin` behaviour. When `cache.set` raises, the response is served with `X-Cache-Status` unchanged (`MISS`, `BYPASS` or `REFRESH`), and a warning is logged on logger `camp.utils.views`.

- [ ] **Step 1: Write the failing test**

Append to `camp/utils/tests/test_cached_endpoint.py`:

```python
class CacheWriteFailureTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()
        cache.clear()

    def test_a_failed_write_serves_the_response_uncached(self):
        # memcached refuses items over 1 MB ("Too large"); that must never
        # turn into a 500 for the reader.
        from unittest.mock import patch

        request = self.factory.get(reverse('api:v2:monitors:monitor-list'))
        with patch('camp.utils.views.cache.set', side_effect=Exception('Too large.')):
            with self.assertLogs('camp.utils.views', level='WARNING') as logs:
                response = monitor_list(request)
        assert response.status_code == 200
        assert response['X-Cache-Status'] == 'MISS'
        assert 'Too large' in logs.output[0]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `$TEST camp/utils/tests/test_cached_endpoint.py -k failed_write`
Expected: FAIL. The exception propagates, or no log is recorded.

- [ ] **Step 3: Implement**

In `camp/utils/views.py`:
- Add `import logging` after `import hashlib`.
- Add `logger = logging.getLogger(__name__)` after the imports.
- In `CachedEndpointMixin.get`, replace

```python
        if self.is_cacheable(response):
            cache.set(cache_key, response, self.cache_timeout)
```

with

```python
        if self.is_cacheable(response):
            try:
                cache.set(cache_key, response, self.cache_timeout)
            except Exception as err:
                # A cache that won't take the item (memcached's 1 MB limit, a
                # backend hiccup) is a miss next time, never an error now.
                logger.warning('Could not cache %s: %s', cache_key, err)
```

- [ ] **Step 4: Run the tests**

Run: `$TEST camp/utils/tests/test_cached_endpoint.py`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git -C <worktree> add camp/utils/views.py camp/utils/tests/test_cached_endpoint.py
git -C <worktree> commit -m "fix(api): a failed cache write serves the response uncached instead of a 500"
```

---

### Task 2: Current-vintage regions and simplified shapes

**Files:**
- Modify: `camp/apps/regions/querysets.py` (`RegionQuerySet.current_vintage`)
- Create: `camp/apps/regions/shapes.py`
- Modify: `camp/api/v2/regions/endpoints.py` (`RegionGeoJSONBase`: vintage filter, `simplify`)
- Test: `camp/api/v2/regions/tests.py`

**Interfaces:**
- Produces:
  - `regions.querysets.TRACT_VINTAGE = '2020'`.
  - `RegionQuerySet.current_vintage()`: excludes tracts whose current boundary version isn't `TRACT_VINTAGE`; other types pass through.
  - `regions.shapes.region_feature(region, geometry_dict) -> dict`: a GeoJSON Feature with `id` = sqid and properties `{id, name, slug, type}`.
  - `regions.shapes.full_geometry(region) -> dict`: a GeoJSON MultiPolygon in 4326, rounded to 5 places.
  - `regions.shapes.simplified_features(region_type) -> list[dict]`: every current-vintage region of the type with a boundary, coverage-simplified together, rounded, sorted by name, cached a day.
  - `regions.shapes.TOLERANCES`: degrees per type; the default is `DEFAULT_TOLERANCE = 0.0005`.
  - Endpoint: `GET /api/2.0/regions/geojson/?type=…[&simplify=1][&slug=&name=&within=]`.

- [ ] **Step 1: Write the failing tests**

In `camp/api/v2/regions/tests.py`, add to `RegionGeoJSONTests`:

```python
    def test_retired_tracts_are_left_out(self):
        current = make_tract('Tract 2020', FRESNO_TRACT_WKT)
        retired = make_tract('Tract 2010', KERN_TRACT_WKT)
        retired.boundary.version = '2010'
        retired.boundary.save(update_fields=['version'])
        _, data = self.get({'type': 'tract'})
        slugs = {f['properties']['slug'] for f in data['features']}
        assert current.slug in slugs and retired.slug not in slugs

    def test_simplified_shapes_share_their_borders(self):
        # Two tracts sharing the edge x = -120.1: simplified together, the
        # shared edge must come out identical on both sides (no gap, no
        # doubled line), and the result is lighter than the input.
        left = 'MULTIPOLYGON(((-120.2 36.8, -120.1 36.8, ' + ', '.join(
            f'-120.1 {36.8 + i * 0.0001:.4f}' for i in range(1, 2000)) + ', -120.1 37.0, -120.2 37.0, -120.2 36.8)))'
        right = 'MULTIPOLYGON(((-120.1 36.8, -120.0 36.8, -120.0 37.0, -120.1 37.0, ' + ', '.join(
            f'-120.1 {37.0 - i * 0.0001:.4f}' for i in range(1, 2000)) + ', -120.1 36.8)))'
        make_tract('Left', left)
        make_tract('Right', right)
        _, data = self.get({'type': 'tract', 'simplify': '1'})
        rings = {f['properties']['slug']: f['geometry']['coordinates'][0][0] for f in data['features']}
        on_edge = lambda ring: sorted({tuple(p) for p in ring if p[0] == -120.1})
        assert on_edge(rings['left']) == on_edge(rings['right'])
        assert len(rings['left']) < 100

    def test_simplified_keeps_the_filters(self):
        _, data = self.get({'type': 'county', 'slug': 'fresno', 'simplify': '1'})
        assert [f['properties']['slug'] for f in data['features']] == ['fresno']
        assert data['features'][0]['geometry']['type'] == 'MultiPolygon'
```

At the top of the class module, `make_tract`, `FRESNO_TRACT_WKT` and `KERN_TRACT_WKT` already exist. `setUp` clears the cache.

- [ ] **Step 2: Run them to verify they fail**

Run: `$TEST camp/api/v2/regions/tests.py -k "retired or simplified"`
Expected: FAIL. The retired tract is included, and `simplify` is ignored.

- [ ] **Step 3: `current_vintage()`**

In `camp/apps/regions/querysets.py`, add `from django.db.models import Q` beside the other imports. Add this module constant above the class:

```python
# The census tract vintage every current feature uses (the ACS and
# CalEnviroScreen 5 are on 2020 tracts). Tracts whose current boundary is an
# older vintage are retired: kept for CalEnviroScreen 4, never shown.
TRACT_VINTAGE = '2020'
```

and this method on `RegionQuerySet`:

```python
    def current_vintage(self):
        """Leave out retired census tracts (see TRACT_VINTAGE); other types pass through."""
        from camp.apps.regions.models import Region

        return self.exclude(Q(type=Region.Type.TRACT) & ~Q(boundary__version=TRACT_VINTAGE))
```

- [ ] **Step 4: `camp/apps/regions/shapes.py`**

```python
"""
Region outlines as GeoJSON features for maps.

Full precision is exact but heavy (the eight counties are ~850 KB, the ZIP
areas ~10 MB). Simplified shapes run a whole region type through
shapely.coverage_simplify together, so neighbours keep one identical shared
border -- simplifying each shape on its own leaves gaps and doubled lines
where they meet. Each type's simplified set is computed once and cached,
zlib-compressed, for a day.
"""
import json
import zlib

import shapely
from shapely import wkb

from django.core.cache import cache

from camp.apps.regions.models import Region
from camp.utils.gis import EPSG_LATLON, round_coords

# Degrees. ~0.0005 is about 50 m at the valley's latitude: invisible at the
# zooms an area map is read at. Counties get a finer line; they're few.
DEFAULT_TOLERANCE = 0.0005
TOLERANCES = {Region.Type.COUNTY: 0.0002}
SHAPES_TTL = 60 * 60 * 24
SHAPES_KEY = 'regions:v1:simplified:{type}'


def _latlon(geometry):
    if geometry.srid and geometry.srid != EPSG_LATLON:
        geometry = geometry.transform(EPSG_LATLON, clone=True)
    return geometry


def _as_multipolygon(geojson):
    if geojson['type'] == 'Polygon':
        return {'type': 'MultiPolygon', 'coordinates': [geojson['coordinates']]}
    return geojson


def region_feature(region, geometry):
    properties = {'id': region.sqid, 'name': region.name, 'slug': region.slug, 'type': region.type}
    return {'type': 'Feature', 'id': region.sqid, 'geometry': geometry, 'properties': properties}


def full_geometry(region):
    geometry = _latlon(region.boundary.geometry)
    return round_coords(_as_multipolygon(json.loads(geometry.geojson)))


def _simplify(regions, tolerance):
    shapes = [wkb.loads(bytes(_latlon(region.boundary.geometry).wkb)) for region in regions]
    try:
        simplified = shapely.coverage_simplify(shapes, tolerance)
    except shapely.errors.GEOSException:
        # Not a clean coverage (overlaps): fall back to shape by shape.
        simplified = [shapely.simplify(shape, tolerance, preserve_topology=True) for shape in shapes]
    return [round_coords(_as_multipolygon(json.loads(shapely.to_geojson(shape)))) for shape in simplified]


def simplified_features(region_type):
    """Every current region of the type with a boundary, simplified together, sorted by name."""
    key = SHAPES_KEY.format(type=region_type)
    packed = cache.get(key)
    if packed is not None:
        return json.loads(zlib.decompress(packed))
    regions = list(
        Region.objects.filter(type=region_type, boundary__isnull=False)
        .current_vintage().select_related('boundary').order_by('name')
    )
    geometries = _simplify(regions, TOLERANCES.get(region_type, DEFAULT_TOLERANCE)) if regions else []
    features = [region_feature(region, geometry) for region, geometry in zip(regions, geometries)]
    try:
        cache.set(key, zlib.compress(json.dumps(features).encode()), SHAPES_TTL)
    except Exception:
        pass  # Too big to cache: computed again next time, never an error.
    return features
```

- [ ] **Step 5: The endpoint uses them**

In `camp/api/v2/regions/endpoints.py`, replace `RegionGeoJSONBase.get` and `feature`, and drop the now-unused `MultiPolygon`, `EPSG_LATLON` and `round_coords` imports. Import `from camp.apps.regions import shapes`. Then:

```python
    def get(self, request, *args, **kwargs):
        # Unfiltered this is every region in the database -- thousands of
        # square-mile sections among them -- so a type is required.
        region_type = request.GET.get('type', '').strip()
        if not region_type:
            return http.Http400({'error': 'The type parameter is required.'})
        regions = (
            self.filter_queryset(self.get_queryset())
            .exclude(boundary=None).current_vintage().order_by('name')
        )
        if request.GET.get('simplify') == '1':
            # The whole type is simplified together (shared borders stay
            # shared); the filters then pick from it.
            wanted = set(regions.values_list('sqid', flat=True))
            features = [f for f in shapes.simplified_features(region_type) if f['id'] in wanted]
        else:
            features = [shapes.region_feature(region, shapes.full_geometry(region)) for region in regions]
        return {'type': 'FeatureCollection', 'features': features}
```

Bump `RegionGeoJSON.cache_key_version` to `2`, and extend its docstring: `?simplify=1 returns shapes simplified together (for area maps).`

- [ ] **Step 6: Run the tests**

Run: `$TEST camp/api/v2/regions/tests.py`
Expected: all PASS.

- [ ] **Step 7: Measure on local data**

```bash
C=$(docker ps --filter publish=8003 --format '{{.Names}}')
for t in county zipcode tract; do curl -s -o /dev/null -w "$t: %{size_download} bytes %{http_code}\n" "http://localhost:8003/api/2.0/regions/geojson/?type=$t&simplify=1"; done
```

Expected:
- All three return 200.
- Each body is under 900 KB (memcached's 1 MB item limit, with headroom for pickling).

If `zipcode` or `tract` is larger, raise that type's entry in `TOLERANCES`, e.g. `Region.Type.ZIPCODE: 0.001`, and re-measure (add `&_cc=1` to bypass the cached response). Record the final sizes in the commit message.

- [ ] **Step 8: Commit**

```bash
git -C <worktree> add camp/apps/regions/querysets.py camp/apps/regions/shapes.py camp/api/v2/regions/endpoints.py camp/api/v2/regions/tests.py
git -C <worktree> commit -m "feat(regions): 2020-only tracts, and coverage-simplified shapes for area maps

Local sizes (simplify=1): county <n> KB, zipcode <n> KB, tract <n> KB."
```

Replace each `<n>` with the Step 7 measurements.

---

### Task 3: ACS population

**Files:**
- Create: `camp/apps/regions/management/commands/import_population.py`
- Create: `camp/apps/regions/population.py`
- Test: `camp/apps/regions/tests/test_population.py`

**Interfaces:**
- Produces:
  - `regions.population.ACS_YEAR = 2024`.
  - `regions.population.fetch(geography, year) -> {geoid: int}`, where geography is `'county'`, `'zipcode'` or `'tract'`.
  - `regions.population.apply(region_type, counts) -> (updated, missing)`: writes `Region.metadata['population']`, matching `Region.external_id` to the GEOID (5-digit county, 5-digit ZCTA, 11-digit tract).
  - Command: `python manage.py import_population [--year 2024]`.

- [ ] **Step 1: Write the failing tests**

```python
from unittest.mock import MagicMock, patch

from django.contrib.gis.geos import GEOSGeometry
from django.core.management import call_command
from django.test import TestCase

from camp.apps.regions import population
from camp.apps.regions.models import Boundary, Region


def response(rows):
    mock = MagicMock()
    mock.raise_for_status.return_value = None
    mock.json.return_value = rows
    return mock


def make(region_type, name, external_id, version='2020'):
    region = Region.objects.create(name=name, slug=name.lower(), type=region_type, external_id=external_id)
    boundary = Boundary.objects.create(region=region, version=version, geometry=GEOSGeometry(
        'MULTIPOLYGON(((-120 36, -119 36, -119 37, -120 37, -120 36)))', srid=4326))
    region.boundary = boundary
    region.save(update_fields=['boundary'])
    return region


class PopulationTests(TestCase):
    def test_fetch_builds_geoids_per_geography(self):
        rows = {
            'county': [['B01003_001E', 'state', 'county'], ['1017162', '06', '019']],
            'zipcode': [['B01003_001E', 'zip code tabulation area'], ['52131', '93725']],
            'tract': [['B01003_001E', 'state', 'county', 'tract'], ['4321', '06', '019', '000100']],
        }
        for geography, expected in (('county', {'06019': 1017162}), ('zipcode', {'93725': 52131}),
                                    ('tract', {'06019000100': 4321})):
            with patch('requests.get', return_value=response(rows[geography])) as get:
                assert population.fetch(geography, 2024) == expected
            assert '/2024/acs/acs5' in get.call_args[0][0]

    def test_apply_writes_metadata_and_counts_misses(self):
        fresno = make(Region.Type.COUNTY, 'Fresno', '06019')
        make(Region.Type.COUNTY, 'Nowhere', '06999')
        updated, missing = population.apply(Region.Type.COUNTY, {'06019': 1017162})
        fresno.refresh_from_db()
        assert fresno.metadata['population'] == 1017162
        assert (updated, missing) == (1, 1)

    def test_retired_tracts_are_skipped(self):
        make(Region.Type.TRACT, 'Old', '06019999999', version='2010')
        updated, missing = population.apply(Region.Type.TRACT, {'06019999999': 10})
        assert (updated, missing) == (0, 0)

    def test_command(self):
        make(Region.Type.COUNTY, 'Fresno', '06019')
        with patch.object(population, 'fetch', return_value={'06019': 5}) as fetch:
            call_command('import_population', '--year', '2023')
        assert fetch.call_count == 3
        assert Region.objects.get(external_id='06019').metadata['population'] == 5
```

- [ ] **Step 2: Run them to verify they fail**

Run: `$TEST camp/apps/regions/tests/test_population.py`
Expected: `ImportError: cannot import name 'population'`.

- [ ] **Step 3: `camp/apps/regions/population.py`**

```python
"""
Total population (ACS 5-year, table B01003) for counties, ZIP areas (ZCTAs)
and 2020 census tracts, stored as Region.metadata['population']. One Census
API request per geography; no key needed at this volume.
"""
import requests

from django.db import transaction

from camp.apps.regions.models import Region

ACS_YEAR = 2024
URL = 'https://api.census.gov/data/{year}/acs/acs5'
VARIABLE = 'B01003_001E'
STATE = '06'
# Region type -> (Census `for`/`in` parameters, columns that make the GEOID).
GEOGRAPHIES = {
    'county': (Region.Type.COUNTY, {'for': 'county:*', 'in': f'state:{STATE}'}, ('state', 'county')),
    'zipcode': (Region.Type.ZIPCODE, {'for': 'zip code tabulation area:*'}, ('zip code tabulation area',)),
    'tract': (Region.Type.TRACT, {'for': 'tract:*', 'in': [f'state:{STATE}', 'county:*']}, ('state', 'county', 'tract')),
}


def fetch(geography, year=ACS_YEAR):
    _, params, geoid_columns = GEOGRAPHIES[geography]
    response = requests.get(URL.format(year=year), params={'get': VARIABLE, **params}, timeout=120)
    response.raise_for_status()
    header, *rows = response.json()
    value_at = header.index(VARIABLE)
    geoid_at = [header.index(column) for column in geoid_columns]
    counts = {}
    for row in rows:
        try:
            counts[''.join(row[i] for i in geoid_at)] = int(row[value_at])
        except (TypeError, ValueError):
            continue  # Census marks suppressed values with negative sentinels or nulls.
    return counts


def apply(region_type, counts):
    """Write each current region's population; returns (updated, missing from the ACS)."""
    updated = missing = 0
    with transaction.atomic():
        for region in Region.objects.filter(type=region_type).current_vintage():
            value = counts.get(region.external_id or '')
            if value is None or value < 0:
                missing += 1
                continue
            region.metadata = {**(region.metadata or {}), 'population': value}
            region.save(update_fields=['metadata'])
            updated += 1
    return updated, missing
```

- [ ] **Step 4: The command**

```python
from django.core.management.base import BaseCommand

from camp.apps.regions import population


class Command(BaseCommand):
    help = (
        "Load ACS 5-year total population (B01003) into Region.metadata['population'] "
        'for counties, ZIP areas and 2020 census tracts. Safe to re-run; re-run when a '
        'new ACS 5-year release lands.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--year', type=int, default=population.ACS_YEAR, help='ACS 5-year release (end year)')

    def handle(self, *args, **options):
        for geography, (region_type, _, _) in population.GEOGRAPHIES.items():
            counts = population.fetch(geography, options['year'])
            updated, missing = population.apply(region_type, counts)
            self.stdout.write(f'{geography}: {updated} updated, {missing} not in the ACS')
```

- [ ] **Step 5: Run the tests**

Run: `$TEST camp/apps/regions/tests/test_population.py`
Expected: all PASS.

- [ ] **Step 6: Run it locally**

Run: `docker exec <8003 container> python manage.py import_population`

Expected: nonzero "updated" for all three geographies. Check that the 2024 release exists: a 404 from the Census API means it doesn't, so use `--year 2023`, change `ACS_YEAR`, and note it in the commit. Paste the output into the commit message.

- [ ] **Step 7: Commit**

```bash
git -C <worktree> add camp/apps/regions/population.py camp/apps/regions/management/commands/import_population.py camp/apps/regions/tests/test_population.py
git -C <worktree> commit -m "feat(regions): import_population loads ACS total population for counties, ZIP areas and 2020 tracts"
```

---

### Task 4: Area rollups and area-scoped stats

**Files:**
- Create: `camp/apps/emissions/areas.py`
- Modify: `camp/apps/emissions/stats.py` (`Scope.area`, `Scope.key`, `records`)
- Test: `camp/apps/emissions/tests/test_areas.py`

**Interfaces:**
- Consumes (Task 2): `RegionQuerySet.current_vintage()`, `regions.querysets.TRACT_VINTAGE`. Consumes (Task 3): `Region.metadata['population']`.
- Produces, in `camp/apps/emissions/areas.py`:
  - Constants: `LEVELS`, `DEFAULT_LEVEL = 'zipcode'`, `MEASURES = ('density', 'total', 'per_resident')`, `DEFAULT_MEASURE = 'density'`, `NEXT_LEVEL` (the page type's default map level).
  - `level_regions(level) -> RegionQuerySet`: the current regions of a level that have a boundary.
  - `region_index(level) -> {facility pk: region pk}`, cached a day.
  - `region_sq_miles(level) -> {region pk: float}`, cached a day.
  - `area_values(scope, level, sector=None) -> {'level', 'unit', 'facilities_without_point', 'areas': [{'id', 'facilities', 'total', 'per_sq_mi', 'per_1k_residents'}]}`. `id` is the region sqid; values are in the display unit; cached per scope.
  - `RegionArea(region)` and `RadiusArea(lat, lng, radius)`: frozen dataclasses with `.key` (str), `.q()` (a `Q` on `EmissionsRecord`), `.sq_miles` (float or None) and `.population` (int or None). `RadiusArea` also has `.point`.
  - `facility_areas(facility) -> [Region]`: the facility's county, then its ZIP area and 2020 tract when its point falls in one.
- Produces, in `stats`: `Scope(..., area=None)`. `records(scope)` narrows to `scope.area.q()`, and `scope.key()` includes `area.key`.

- [ ] **Step 1: Write the failing tests**

Create `camp/apps/emissions/tests/test_areas.py`:

```python
from django.contrib.gis.geos import GEOSGeometry
from django.core.cache import cache
from django.test import TestCase

from camp.apps.emissions import areas, stats
from camp.apps.emissions.models import Facility
from camp.apps.regions.models import Boundary, Region

# TEST PLANT is at (-119.787, 36.737): Fresno. TEST CEMENT is at (-118.17, 35.05).
AROUND_PLANT = 'MULTIPOLYGON(((-119.8 36.72, -119.77 36.72, -119.77 36.75, -119.8 36.75, -119.8 36.72)))'
WEST_OF_PLANT = 'MULTIPOLYGON(((-119.8 36.72, -119.787 36.72, -119.787 36.75, -119.8 36.75, -119.8 36.72)))'
EAST_OF_PLANT = 'MULTIPOLYGON(((-119.787 36.72, -119.77 36.72, -119.77 36.75, -119.787 36.75, -119.787 36.72)))'


def make(region_type, name, wkt, *, version='2020', population=None):
    metadata = {'population': population} if population is not None else {}
    region = Region.objects.create(name=name, slug=name.lower().replace(' ', '-'), type=region_type,
                                   external_id=name, metadata=metadata)
    boundary = Boundary.objects.create(region=region, version=version, geometry=GEOSGeometry(wkt, srid=4326))
    region.boundary = boundary
    region.save(update_fields=['boundary'])
    return region


class AreaTestCase(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        cache.clear()
        self.plant = Facility.objects.get(name='TEST PLANT')
        self.cement = Facility.objects.get(name='TEST CEMENT')
        # 2024, NOx: the plant reported 6.0 tons, the cement plant 100.0.
        self.scope = stats.resolve_scope({'year': '2024', 'pollutant': 'nox'})


class RegionIndexTests(AreaTestCase):
    def test_zip_and_tract_by_point(self):
        tract = make(Region.Type.TRACT, 'T1', AROUND_PLANT)
        index = areas.region_index(Region.Type.TRACT)
        assert index[self.plant.pk] == tract.pk
        assert self.cement.pk not in index

    def test_retired_tracts_are_not_used(self):
        make(Region.Type.TRACT, 'Old', AROUND_PLANT, version='2010')
        assert self.plant.pk not in areas.region_index(Region.Type.TRACT)

    def test_a_facility_on_a_shared_border_counts_once(self):
        make(Region.Type.TRACT, 'West', WEST_OF_PLANT)
        make(Region.Type.TRACT, 'East', EAST_OF_PLANT)
        values = areas.area_values(self.scope, Region.Type.TRACT)
        assert sum(area['facilities'] for area in values['areas']) == 1

    def test_county_level_uses_carbs_county_code(self):
        index = areas.region_index(Region.Type.COUNTY)
        assert index[self.plant.pk] == self.plant.county_id
        assert index[self.cement.pk] == self.cement.county_id


class AreaValuesTests(AreaTestCase):
    def test_measures(self):
        tract = make(Region.Type.TRACT, 'T1', AROUND_PLANT, population=2000)
        values = areas.area_values(self.scope, Region.Type.TRACT)
        assert values['level'] == 'tract' and values['unit'] == 'tons'
        [area] = values['areas']
        miles = areas.region_sq_miles(Region.Type.TRACT)[tract.pk]
        assert area['id'] == tract.sqid
        assert area['facilities'] == 1
        assert area['total'] == 6.0
        assert abs(area['per_sq_mi'] - 6.0 / miles) < 1e-9
        assert area['per_1k_residents'] == 3.0

    def test_no_or_zero_population_has_no_per_resident_value(self):
        make(Region.Type.TRACT, 'West', WEST_OF_PLANT, population=0)
        make(Region.Type.TRACT, 'Far', 'MULTIPOLYGON(((-118.2 35.0, -118.1 35.0, -118.1 35.1, -118.2 35.1, -118.2 35.0)))')
        for area in areas.area_values(self.scope, Region.Type.TRACT)['areas']:
            assert area['per_1k_residents'] is None

    def test_toxics_in_pounds(self):
        make(Region.Type.TRACT, 'T1', AROUND_PLANT)
        scope = stats.resolve_scope({'year': '2024', 'toxics': '1'})
        assert areas.area_values(scope, Region.Type.TRACT)['unit'] == 'lbs'

    def test_sector_filter(self):
        make(Region.Type.TRACT, 'T1', AROUND_PLANT)
        assert areas.area_values(self.scope, Region.Type.TRACT, sector='cement-minerals')['areas'] == []


class ScopeAreaTests(AreaTestCase):
    def test_region_area_narrows_every_aggregate(self):
        tract = make(Region.Type.TRACT, 'T1', AROUND_PLANT, population=1500)
        scope = stats.Scope(year=2024, county=None, pollutant=self.scope.pollutant, area=areas.RegionArea(tract))
        assert stats.totals(scope)['facilities'] == 1
        assert stats.totals(scope)['nox'] == 6.0
        assert scope.key('totals') != self.scope.key('totals')
        assert scope.area.population == 1500 and scope.area.sq_miles > 0

    def test_city_area_is_by_point(self):
        city = make(Region.Type.CITY, 'Somewhere', AROUND_PLANT)
        scope = stats.Scope(year=2024, county=None, pollutant=self.scope.pollutant, area=areas.RegionArea(city))
        assert stats.totals(scope)['facilities'] == 1

    def test_radius_area(self):
        near = areas.RadiusArea(36.737, -119.787, 1)
        scope = stats.Scope(year=2024, county=None, pollutant=self.scope.pollutant, area=near)
        assert stats.totals(scope)['facilities'] == 1
        assert abs(near.sq_miles - 3.14159) < 0.001

    def test_facility_areas(self):
        # The fixture's ZIP 93728 contains the plant too; start from none.
        Region.objects.filter(type=Region.Type.ZIPCODE).delete()
        zipcode = make(Region.Type.ZIPCODE, '93701', AROUND_PLANT)
        tract = make(Region.Type.TRACT, 'T1', AROUND_PLANT)
        assert areas.facility_areas(self.plant) == [self.plant.county, zipcode, tract]
        assert areas.facility_areas(self.cement) == [self.cement.county]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `$TEST camp/apps/emissions/tests/test_areas.py`
Expected: `ImportError: cannot import name 'areas'`.

- [ ] **Step 3: `Scope.area` in `stats.py`**

In `camp/apps/emissions/stats.py`:
- Add the field `area: Optional[object] = None` after `minor: bool = False` in `Scope`, with the comment `# A region or radius the scope is narrowed to (areas.RegionArea / areas.RadiusArea).`
- In `Scope.key`, change the `parts` list to include `self.area.key if self.area is not None else 'anywhere'` right after `int(self.minor)`.
- In `records()`, after the county filter, add:

```python
    if scope.area is not None:
        queryset = queryset.filter(scope.area.q())
```

`params()` and `query()` are unchanged: an area comes from the page's URL path, never the query string.

- [ ] **Step 4: `camp/apps/emissions/areas.py`**

```python
"""
Emissions by area.

Which ZIP area and census tract each facility's point falls in, the totals
the map's Areas view shades, and the Area objects that narrow a stats.Scope
to one region or a radius (region pages, near-me).

Counties count by CARB's county code (Facility.county); ZIP areas, tracts and
every other region type by the facility's point. Facility data is never
rewritten: the point-to-region mapping is computed and cached.
"""
import math
from dataclasses import dataclass

from django.contrib.gis.db.models.functions import Area as AreaOf, Transform
from django.contrib.gis.geos import Point, Polygon
from django.contrib.gis.measure import D
from django.core.cache import cache
from django.db.models import OuterRef, Q, Subquery

from camp.apps.emissions import stats
from camp.apps.emissions.models import Facility
from camp.apps.regions.models import Region
from camp.utils.gis import EPSG_CALIFORNIA_ALBERS, EPSG_LATLON

LEVELS = (Region.Type.COUNTY, Region.Type.ZIPCODE, Region.Type.TRACT)
DEFAULT_LEVEL = Region.Type.ZIPCODE
MEASURES = ('density', 'total', 'per_resident')
DEFAULT_MEASURE = 'density'
# The map level a region page opens its Areas view at: one step finer than
# the page. A tract page has none (it's the finest level).
NEXT_LEVEL = {
    Region.Type.COUNTY: Region.Type.ZIPCODE,
    Region.Type.CITY: Region.Type.TRACT,
    Region.Type.ZIPCODE: Region.Type.TRACT,
    Region.Type.PLACE: Region.Type.TRACT,
    Region.Type.SCHOOL_DISTRICT: Region.Type.TRACT,
}
SQ_METERS_PER_SQ_MILE = 2_589_988.110336
MILES_PER_DEGREE = 69.0


def _key(name, *parts):
    return ':'.join(str(part) for part in (f'emissions:v{stats.CACHE_VERSION}', name, *parts))


def level_regions(level):
    """The regions an Areas level shades: covered counties, ZIP areas, 2020 tracts."""
    queryset = Region.objects.counties() if level == Region.Type.COUNTY else Region.objects.filter(type=level)
    return queryset.filter(boundary__isnull=False).current_vintage()


def region_index(level):
    """
    {facility pk: region pk} for one level. Counties by Facility.county;
    otherwise the region the facility's point falls in (`intersects`, so a
    point exactly on a shared border still lands somewhere, and `[:1]` so it
    lands in only one). Facilities without a point are only in counties.
    """
    def compute():
        if level == Region.Type.COUNTY:
            return dict(Facility.objects.exclude(county=None).values_list('pk', 'county_id'))
        containing = (
            level_regions(level).filter(boundary__geometry__intersects=OuterRef('point'))
            .order_by('pk').values('pk')[:1]
        )
        rows = Facility.objects.exclude(point=None).annotate(region_pk=Subquery(containing)).values_list('pk', 'region_pk')
        return {facility: region for facility, region in rows if region is not None}
    return cache.get_or_set(_key('region-index', level), compute, stats.CACHE_TIMEOUT)


def region_sq_miles(level):
    """{region pk: square miles}, from the full boundary in California Albers."""
    def compute():
        rows = (
            level_regions(level)
            .annotate(area=AreaOf(Transform('boundary__geometry', EPSG_CALIFORNIA_ALBERS)))
            .values_list('pk', 'area')
        )
        return {pk: area.sq_m / SQ_METERS_PER_SQ_MILE for pk, area in rows if area}
    return cache.get_or_set(_key('region-sq-miles', level), compute, stats.CACHE_TIMEOUT)


def _per(total, divisor, scale=1):
    return total / divisor * scale if total is not None and divisor else None


def area_values(scope, level, sector=None):
    """What the Areas view shades: per region with facilities in scope, its count, total and the two rates."""
    field = scope.pollutant.key

    def compute():
        index = region_index(level)
        rows = stats.records(scope)
        if sector:
            rows = rows.filter(facility__sector=sector)
        counts, sums = {}, {}
        for facility_id, value in rows.values_list('facility_id', field):
            region = index.get(facility_id)
            if region is None:
                continue
            counts[region] = counts.get(region, 0) + 1
            sums[region] = sums.get(region, 0.0) + float(value or 0)
        miles = region_sq_miles(level)
        regions = Region.objects.filter(pk__in=counts).values_list('pk', 'sqid', 'metadata')
        result = []
        for pk, sqid, metadata in regions:
            total = scope.pollutant.display(sums[pk])
            result.append({
                'id': sqid,
                'facilities': counts[pk],
                'total': total,
                'per_sq_mi': _per(total, miles.get(pk)),
                'per_1k_residents': _per(total, (metadata or {}).get('population'), 1000),
            })
        result.sort(key=lambda area: area['id'])
        without_point = 0 if level == Region.Type.COUNTY else rows.filter(facility__point=None).count()
        return {'level': level, 'unit': scope.pollutant.unit, 'facilities_without_point': without_point, 'areas': result}
    return cache.get_or_set(scope.key('areas', level, sector or ''), compute, stats.CACHE_TIMEOUT)


@dataclass(frozen=True)
class RegionArea:
    """A Scope narrowed to one region (a region page)."""
    region: Region

    @property
    def key(self):
        return f'region-{self.region.pk}'

    def q(self):
        region = self.region
        if region.type == Region.Type.COUNTY:
            return Q(facility__county=region)
        if region.type in LEVELS:
            ids = [facility for facility, pk in region_index(region.type).items() if pk == region.pk]
            return Q(facility_id__in=ids)
        return Q(facility__point__intersects=region.boundary.geometry)

    @property
    def sq_miles(self):
        if self.region.type in LEVELS:
            return region_sq_miles(self.region.type).get(self.region.pk)
        geometry = self.region.boundary.geometry.transform(EPSG_CALIFORNIA_ALBERS, clone=True)
        return geometry.area / SQ_METERS_PER_SQ_MILE

    @property
    def population(self):
        return (self.region.metadata or {}).get('population')


@dataclass(frozen=True)
class RadiusArea:
    """A Scope narrowed to a circle around a point (near-me)."""
    lat: float
    lng: float
    radius: int

    @property
    def key(self):
        return f'near-{self.lat:.4f}-{self.lng:.4f}-{self.radius}'

    @property
    def point(self):
        return Point(self.lng, self.lat, srid=EPSG_LATLON)

    def q(self):
        # A bounding-box prefilter first, so the index does the work and the
        # exact distance runs on a handful of rows.
        dlat = self.radius / MILES_PER_DEGREE
        dlng = self.radius / (MILES_PER_DEGREE * max(math.cos(math.radians(self.lat)), 0.01))
        box = Polygon.from_bbox((self.lng - dlng, self.lat - dlat, self.lng + dlng, self.lat + dlat))
        box.srid = EPSG_LATLON
        return Q(facility__point__bboverlaps=box, facility__point__distance_lte=(self.point, D(mi=self.radius)))

    @property
    def sq_miles(self):
        return math.pi * self.radius ** 2

    @property
    def population(self):
        return None


def facility_areas(facility):
    """The regions a facility counts in: its county, then the ZIP area and tract its point is in."""
    pks = [facility.county_id] if facility.county_id else []
    for level in (Region.Type.ZIPCODE, Region.Type.TRACT):
        pk = region_index(level).get(facility.pk)
        if pk:
            pks.append(pk)
    regions = Region.objects.in_bulk(pks)
    return [regions[pk] for pk in pks if pk in regions]
```

- [ ] **Step 5: Run the tests**

Run: `$TEST camp/apps/emissions`
Expected: all PASS. That includes the existing stats and view tests: nothing sets `area`, so every existing cache key only gains `anywhere`.

- [ ] **Step 6: Time it on local data**

```bash
C=$(docker ps --filter publish=8003 --format '{{.Names}}')
docker exec $C python manage.py shell -c "
import time; from django.core.cache import cache; cache.clear()
from camp.apps.emissions import areas, stats
scope = stats.resolve_scope({})
for level in areas.LEVELS:
    t = time.time(); values = areas.area_values(scope, level)
    print(level, len(values['areas']), 'areas', values['facilities_without_point'], 'without a point', f'{time.time() - t:.2f}s')
"
```

Expected: each level finishes in under 10 s uncached. If a level is slower, stop and report the timings; the spatial index or the query shape needs a look.

- [ ] **Step 7: Commit**

```bash
git -C <worktree> add camp/apps/emissions/areas.py camp/apps/emissions/stats.py camp/apps/emissions/tests/test_areas.py
git -C <worktree> commit -m "feat(emissions): area rollups by facility point, and Scope.area for region and radius pages"
```

---

### Task 5: The area values endpoint

**Files:**
- Create: `camp/api/v2/emissions/areas.py`
- Modify: `camp/api/v2/emissions/urls.py`
- Test: `camp/api/v2/emissions/tests.py`

**Interfaces:**
- Consumes (Task 4): `areas.LEVELS`, `areas.area_values(scope, level, sector)`.
- Produces: `GET /api/2.0/emissions/areas/?level=county|zipcode|tract&year=&pollutant=&toxics=&county=&minor=&sector=`. It returns `area_values()`'s dict, and 400 `{'error': …}` for a missing or unknown level. URL name `api:v2:emissions:areas`.

- [ ] **Step 1: Write the failing tests**

Append to `camp/api/v2/emissions/tests.py`. It already loads the `regions.yaml` and `emissions.yaml` fixtures. If the file has no fixture-loading `TestCase` to copy, declare `fixtures = ['regions.yaml', 'emissions.yaml']`.

```python
class AreaValuesEndpointTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        from django.core.cache import cache
        cache.clear()

    def test_county_values(self):
        response = self.client.get('/api/2.0/emissions/areas/', {'level': 'county', 'year': '2024'})
        assert response.status_code == 200
        data = response.json()
        assert data['level'] == 'county' and data['unit'] == 'tons'
        assert {area['facilities'] for area in data['areas']} >= {1}
        assert set(data['areas'][0]) == {'id', 'facilities', 'total', 'per_sq_mi', 'per_1k_residents'}

    def test_level_is_required_and_checked(self):
        assert self.client.get('/api/2.0/emissions/areas/').status_code == 400
        assert self.client.get('/api/2.0/emissions/areas/', {'level': 'mtrs'}).status_code == 400
```

- [ ] **Step 2: Run them to verify they fail**

Run: `$TEST camp/api/v2/emissions/tests.py -k AreaValues`
Expected: 404s. The route doesn't exist yet.

- [ ] **Step 3: The endpoint**

`camp/api/v2/emissions/areas.py`:

```python
from resticus import generics, http

from camp.apps.emissions import areas, stats
from camp.apps.emissions.models import Facility
from camp.utils.views import CachedEndpointMixin


class AreaValuesBase(generics.Endpoint):
    # get() lives on this un-cached base so CachedEndpointMixin.get() on the
    # subclass is the one dispatched to (the explorer endpoints' pattern).
    def get(self, request):
        level = request.GET.get('level', '')
        if level not in areas.LEVELS:
            return http.Http400({'error': f"level must be one of {', '.join(areas.LEVELS)}."})
        scope = stats.resolve_scope(request.GET)
        sector = request.GET.get('sector')
        sector = sector if sector in Facility.Sector.values else None
        return areas.area_values(scope, level, sector)


class AreaValues(CachedEndpointMixin, AreaValuesBase):
    """
    Per-area emissions for the map's Areas view: ?level= (county, zipcode,
    tract; required) plus the explorer scope (year, county, pollutant,
    toxics=1, minor=1) and sector. Numbers only; shapes come from
    /api/2.0/regions/geojson/?type=<level>&simplify=1, joined on `id`.
    """
    cache_timeout = 60 * 60
    cache_key_version = 1
```

In `camp/api/v2/emissions/urls.py`, add `areas` to the imports (`from . import areas, endpoints, geojson`) and, before `'<str:facility_id>/'`:

```python
    path('areas/', areas.AreaValues.as_view(), name='areas'),
```

- [ ] **Step 4: Run the tests**

Run: `$TEST camp/api/v2/emissions`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git -C <worktree> add camp/api/v2/emissions/areas.py camp/api/v2/emissions/urls.py camp/api/v2/emissions/tests.py
git -C <worktree> commit -m "feat(api): emissions area values for the map's Areas view"
```

---

### Task 6: Region pages, near-me and find-your-area

**Files:**
- Modify: `camp/apps/regions/models.py` (`Region.get_emissions_url`)
- Modify: `camp/apps/emissions/views.py` (`AreaPage`, `RegionPage`, `RegionRedirect`, `NearMe`, `find_area_places`, `Home` context, `facility_map_config` keyword arguments)
- Modify: `camp/apps/emissions/urls.py`
- Create: `camp/templates/emissions/area.html`, `camp/templates/emissions/includes/find-area.html`
- Modify: `camp/templates/emissions/home.html`, `camp/templates/emissions/base.html` (load `js/pesticides/find-area.js`)
- Test: `camp/apps/emissions/tests/test_areas_pages.py`

**Interfaces:**
- Consumes (Task 4): `areas.RegionArea`, `areas.RadiusArea`, `areas.NEXT_LEVEL`, `areas.DEFAULT_LEVEL`, `areas.LEVELS`, `areas.MEASURES`, `areas.DEFAULT_MEASURE`, `stats.Scope(..., area=)`.
- Produces:
  - URLs:
    - `emissions:region` (`region/<sqid>/<slug>/`)
    - `emissions:region-redirect` (`region/<sqid>/`)
    - `emissions:near-me` (`near/?lat=&lng=&radius=1|3|5[&label=]`)
  - `Region.get_emissions_url()`.
  - `views.AREA_PAGE_TYPES`, `views.RADIUS_CHOICES = (1, 3, 5)`.
  - `views.map_view(get, default_level) -> {'view', 'level', 'measure'}`: validated.
  - `facility_map_config(scope, *, mode='full', highlight=None, sector=None, params=None, areas_view=None, outline_url='', center='', zoom='', radius='')`. With `areas_view` (a `map_view()` dict), the map's data attributes add:
    - `areas` = `'1'`
    - `areas-url` (the Task 5 endpoint)
    - `shapes-url` (`/api/2.0/regions/geojson/`)
    - `region-url` (the region-redirect pattern with `{id}`)
    - `view`, `level`, `measure`

    Always added: `outline-url`, `radius`. Task 8's JS reads these; until then they are inert.

- [ ] **Step 1: Write the failing tests**

Create `camp/apps/emissions/tests/test_areas_pages.py`:

```python
import json
import re

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from camp.apps.emissions import views
from camp.apps.emissions.tests.test_areas import AROUND_PLANT, make
from camp.apps.regions.models import Region


def map_data(content, key):
    match = re.search(rf'class="facility-map map-canvas"[^>]*data-{key}="([^"]*)"', content)
    return match.group(1) if match else None


class RegionPageTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        cache.clear()
        self.fresno = Region.objects.get(type=Region.Type.COUNTY, slug='fresno')

    def get(self, region, params=None, status=200):
        response = self.client.get(region.get_emissions_url(), params or {})
        assert response.status_code == status, response.status_code
        return response.content.decode()

    def test_county_page(self):
        content = self.get(self.fresno, {'year': '2024'})
        assert '<h1' in content and 'Fresno County' in content
        assert 'TEST PLANT' in content
        # The page is the area: no county picker in the scope bar.
        assert 'data-scope="county"' not in content
        assert map_data(content, 'areas') == '1'
        assert map_data(content, 'level') == 'zipcode'
        assert map_data(content, 'outline-url') == reverse('api:v2:regions:region-detail', args=[self.fresno.sqid])

    def test_city_page_counts_by_point(self):
        city = Region.objects.get(type=Region.Type.CITY, slug='fresno')
        content = self.get(city, {'year': '2024'})
        assert 'TEST PLANT' in content
        assert map_data(content, 'level') == 'tract'

    def test_tract_page(self):
        tract = make(Region.Type.TRACT, '06019000100', AROUND_PLANT, population=4321)
        tract.metadata = {**tract.metadata, 'namelsad': 'Census Tract 1'}
        tract.save(update_fields=['metadata'])
        content = self.get(tract, {'year': '2024'})
        assert 'Census Tract 1' in content and '4,321' in content
        assert 'TEST PLANT' in content
        assert map_data(content, 'areas') == ''  # the finest level: Facilities only

    def test_retired_tracts_and_other_types_404(self):
        old = make(Region.Type.TRACT, 'Old', AROUND_PLANT, version='2010')
        self.get(old, status=404)
        district = Region.objects.create(name='SJV APCD', slug='sjv-apcd', type=Region.Type.AIR_DISTRICT)
        response = self.client.get(reverse('emissions:region', args=[district.sqid, district.slug]))
        assert response.status_code == 404

    def test_redirects(self):
        wrong = reverse('emissions:region', args=[self.fresno.sqid, 'wrong']) + '?year=2024'
        response = self.client.get(wrong)
        assert response.status_code == 301 and response['Location'] == self.fresno.get_emissions_url() + '?year=2024'
        response = self.client.get(reverse('emissions:region-redirect', args=[self.fresno.sqid]))
        assert response.status_code == 301 and response['Location'] == self.fresno.get_emissions_url()

    def test_view_level_and_measure_from_the_url(self):
        content = self.get(self.fresno, {'view': 'areas', 'level': 'tract', 'measure': 'total'})
        assert (map_data(content, 'view'), map_data(content, 'level'), map_data(content, 'measure')) == ('areas', 'tract', 'total')
        content = self.get(self.fresno, {'view': 'bogus', 'level': 'mtrs', 'measure': 'x'})
        assert (map_data(content, 'view'), map_data(content, 'level'), map_data(content, 'measure')) == ('facilities', 'zipcode', 'density')


class NearMeTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        cache.clear()
        self.url = reverse('emissions:near-me')

    def test_page(self):
        response = self.client.get(self.url, {'lat': '36.737', 'lng': '-119.787', 'radius': '1', 'label': 'near Fresno', 'year': '2024'})
        assert response.status_code == 200
        content = response.content.decode()
        assert 'near Fresno' in content and 'TEST PLANT' in content
        assert map_data(content, 'radius') == '1'
        assert map_data(content, 'center') == '36.7370,-119.7870'

    def test_bad_input_bounces_to_the_find_form(self):
        home = reverse('emissions:home') + '?find=1'
        for params in ({}, {'lat': 'x', 'lng': '1'}, {'lat': '36.7', 'lng': '-119.7', 'radius': '2'},
                       {'lat': '91', 'lng': '0'}, {'lat': 'nan', 'lng': '-119.7'},
                       {'lat': '47.6', 'lng': '-122.3'}):  # Seattle: outside every covered county
            response = self.client.get(self.url, params)
            assert response.status_code == 302 and response['Location'] == home, params

    def test_long_label_is_cut(self):
        response = self.client.get(self.url, {'lat': '36.737', 'lng': '-119.787', 'label': 'x' * 500})
        assert 'x' * 121 not in response.content.decode()


class FindAreaTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def test_home_has_the_search_box_without_tracts(self):
        cache.clear()
        make(Region.Type.TRACT, '06019000100', AROUND_PLANT)
        content = self.client.get(reverse('emissions:home')).content.decode()
        assert f'data-near-url="{reverse("emissions:near-me")}"' in content
        places = json.loads(re.search(r'id="find-area-places"[^>]*>(.*?)</script>', content, re.S).group(1))
        assert {place['type'] for place in places} <= {'county', 'city', 'zipcode', 'place', 'school_district'}
        fresno = next(place for place in places if place['name'] == 'Fresno County')
        assert fresno['url'] == Region.objects.get(type='county', slug='fresno').get_emissions_url()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `$TEST camp/apps/emissions/tests/test_areas_pages.py`
Expected: FAIL (`AttributeError: 'Region' object has no attribute 'get_emissions_url'`).

- [ ] **Step 3: `Region.get_emissions_url`**

In `camp/apps/regions/models.py`, after `Region.get_pesticides_url`:

```python
    def get_emissions_url(self):
        """This region's page in the emissions explorer."""
        return reverse('emissions:region', kwargs={'sqid': self.sqid, 'slug': self.slug})
```

- [ ] **Step 4: Routes**

In `camp/apps/emissions/urls.py`, add after `map/`:

```python
    path('near/', views.NearMe.as_view(), name='near-me'),
    path('region/<str:sqid>/', views.RegionRedirect.as_view(), name='region-redirect'),
    path('region/<str:sqid>/<slug:slug>/', views.RegionPage.as_view(), name='region'),
```

- [ ] **Step 5: Map config keywords**

In `camp/apps/emissions/views.py`, add `import math`, `from django.core.cache import cache` and `from camp.apps.emissions import areas` to the imports. Then add above `facility_map_config`:

```python
def map_view(get, default_level=areas.DEFAULT_LEVEL):
    """The map's view, level and measure from a request's GET, validated; defaults when unknown."""
    view = get.get('view')
    level = get.get('level')
    measure = get.get('measure')
    return {
        'view': view if view in ('facilities', 'areas') else 'facilities',
        'level': level if level in areas.LEVELS else default_level,
        'measure': measure if measure in areas.MEASURES else areas.DEFAULT_MEASURE,
    }
```

Change `facility_map_config`'s signature to

```python
def facility_map_config(scope, *, mode='full', highlight=None, sector=None, params=None, areas_view=None,
                        outline_url='', center='', zoom='', radius=''):
```

`areas_view` is `map_view(...)`'s dict when the Areas view is available, else `None`. In the `config` dict:
- replace the `'center'` and `'zoom'` entries with

```python
        'center': center or (f'{point.y},{point.x}' if point is not None else ''),
        'zoom': zoom or (11 if point is not None else ''),
```

- add, before `'label'`:

```python
        # The region or circle the page is about (region pages, near-me).
        'outline_url': outline_url,
        'radius': radius,
        # The Areas view (the map page, region pages): off where it's None.
        'areas': '1' if areas_view else '',
        'areas_url': reverse('api:v2:emissions:areas') if areas_view else '',
        'shapes_url': reverse('api:v2:regions:region-geojson') if areas_view else '',
        'region_url': reverse('emissions:region-redirect', args=['__id__']).replace('__id__', '{id}') if areas_view else '',
        'view': areas_view['view'] if areas_view else 'facilities',
        'level': areas_view['level'] if areas_view else '',
        'measure': areas_view['measure'] if areas_view else '',
```

`MapPage.get_context_data` passes `areas_view=map_view(self.request.GET)`.

- [ ] **Step 6: The views**

Add to `camp/apps/emissions/views.py` (after `MapPage`):

```python
AREA_PAGE_TYPES = (
    Region.Type.COUNTY, Region.Type.CITY, Region.Type.ZIPCODE, Region.Type.PLACE,
    Region.Type.SCHOOL_DISTRICT, Region.Type.TRACT,
)
# The search box lists every page type but tracts: a tract's name is its GEOID.
FIND_AREA_TYPE_LABELS = {
    Region.Type.COUNTY: 'County',
    Region.Type.CITY: 'City',
    Region.Type.ZIPCODE: 'ZIP',
    Region.Type.PLACE: 'Place',
    Region.Type.SCHOOL_DISTRICT: 'School district',
}
FIND_AREA_PLACES_KEY = f'emissions:v{stats.CACHE_VERSION}:find-area-places'
RADIUS_CHOICES = (1, 3, 5)
RADIUS_ZOOMS = {1: 13, 3: 12, 5: 11}
MAX_LABEL = 120


def find_area_places():
    """Every region page but tracts, as {name, type, type_label, short_name, url}, for the search box."""
    def compute():
        regions = (
            Region.objects.filter(type__in=FIND_AREA_TYPE_LABELS, boundary__isnull=False)
            .order_by('name').values_list('sqid', 'slug', 'name', 'type')
        )
        places = [{
            'name': name,
            'type': region_type,
            'type_label': FIND_AREA_TYPE_LABELS[region_type],
            'short_name': name[:-len(' County')] if name.endswith(' County') else name,
            'url': reverse('emissions:region', kwargs={'sqid': sqid, 'slug': slug}),
        } for sqid, slug, name, region_type in regions]
        # Synthetic places share their names with the cities they were built
        # from; "Selma · City" beside "Selma · Place" only confuses.
        cities = {place['name'] for place in places if place['type'] == Region.Type.CITY}
        return [p for p in places if not (p['type'] == Region.Type.PLACE and p['name'] in cities)]
    return cache.get_or_set(FIND_AREA_PLACES_KEY, compute, stats.CACHE_TIMEOUT)


def region_title(region):
    if region.type == Region.Type.TRACT:
        return (region.metadata or {}).get('namelsad') or f'Census tract {region.name}'
    return region.name


class AreaPage(ScopeMixin, vanilla.TemplateView):
    """What a region page and near-me share: one area's facilities, totals, map, sectors and trend."""
    template_name = 'emissions/area.html'

    def get_area(self):
        raise NotImplementedError

    def get_county(self):
        """The county the page's share is of."""
        raise NotImplementedError

    def get_map_config(self, scope):
        raise NotImplementedError

    def get_context_data(self, **kwargs):
        base = self.get_scope()
        area = self.get_area()
        scope = stats.Scope(year=base.year, county=None, pollutant=base.pollutant, minor=base.minor, area=area)
        field = scope.pollutant.key
        totals = stats.totals(scope)
        total = totals[field] or 0
        county = self.get_county()
        county_scope = stats.Scope(year=base.year, county=county, pollutant=base.pollutant, minor=base.minor)
        county_total = stats.totals(county_scope)[field] if county else None
        return super().get_context_data(
            area=area,
            county_region=county,
            totals=totals,
            total=total,
            per_sq_mi=total / area.sq_miles if area.sq_miles else None,
            county_share=total / county_total if county_total else None,
            top_rows=stats.with_ranks(stats.facility_table(scope)[:10], stats.ranks(scope)),
            top_sectors=stats.sector_breakdown(scope),
            by_year=stats.by_year(scope),
            map_config=self.get_map_config(base),
            # The page is the area: no county picker, and the scope links
            # leave the county out.
            county_options=[],
            scope_qs=base.query(county=None),
            scope_params=base.params(county=None),
            **kwargs,
        )


class RegionRedirect(vanilla.View):
    """`region/<sqid>/` -> the slugged URL, keeping the query string (the map's popups link here)."""

    def get(self, request, sqid):
        region = Region.objects.filter(sqid=sqid, type__in=AREA_PAGE_TYPES).first()
        if region is None:
            raise Http404('No such region.')
        query = request.GET.urlencode()
        return redirect(region.get_emissions_url() + (f'?{query}' if query else ''), permanent=True)


class RegionPage(AreaPage):
    def get(self, request, sqid, slug):
        self.region = (
            Region.objects.filter(sqid=sqid, type__in=AREA_PAGE_TYPES, boundary__isnull=False)
            .current_vintage().select_related('boundary').first()
        )
        if self.region is None:
            raise Http404('No such region.')
        if slug != self.region.slug:
            query = request.GET.urlencode()
            return redirect(self.region.get_emissions_url() + (f'?{query}' if query else ''), permanent=True)
        return super().get(request, sqid=sqid, slug=slug)

    def get_area(self):
        return areas.RegionArea(self.region)

    def get_county(self):
        if self.region.type == Region.Type.COUNTY:
            return self.region
        return Region.objects.get_county_region(self.region)

    def get_map_config(self, scope):
        level = areas.NEXT_LEVEL.get(self.region.type)
        return facility_map_config(
            scope, mode='compact', params=scope.params(county=None),
            areas_view=map_view(self.request.GET, level) if level else None,
            outline_url=reverse('api:v2:regions:region-detail', args=[self.region.sqid]),
        )

    def get_context_data(self, **kwargs):
        region = self.region
        return super().get_context_data(
            title=region_title(region),
            kind=region.get_type_display(),
            population=(region.metadata or {}).get('population'),
            context_bar=stats.county_context(stats.Scope(
                year=self.get_scope().year, county=region, pollutant=self.get_scope().pollutant,
                minor=self.get_scope().minor,
            )) if region.type == Region.Type.COUNTY else None,
            **kwargs,
        )


class NearMe(AreaPage):
    """
    The area page for a point and a 1, 3 or 5 mile radius, from the address
    bar (?lat=&lng=&radius=&label=); never stored. Anything invalid, or a
    point outside the covered counties, bounces to the home page's find form.
    """

    def get(self, request, *args, **kwargs):
        try:
            lat = float(request.GET['lat'])
            lng = float(request.GET['lng'])
            radius = int(request.GET.get('radius', 1))
        except (KeyError, TypeError, ValueError):
            return self.bounce()
        if not (math.isfinite(lat) and math.isfinite(lng) and -90 <= lat <= 90 and -180 <= lng <= 180):
            return self.bounce()
        if radius not in RADIUS_CHOICES:
            return self.bounce()
        self.near = areas.RadiusArea(round(lat, 4), round(lng, 4), radius)
        self.county = Region.objects.counties().filter(boundary__geometry__intersects=self.near.point).first()
        if self.county is None:
            return self.bounce()
        return super().get(request, *args, **kwargs)

    def bounce(self):
        return redirect(reverse('emissions:home') + '?find=1')

    def get_area(self):
        return self.near

    def get_county(self):
        return self.county

    def get_map_config(self, scope):
        return facility_map_config(
            scope, mode='compact', params=scope.params(county=None),
            areas_view=map_view(self.request.GET, Region.Type.TRACT),
            center=f'{self.near.lat:.4f},{self.near.lng:.4f}', zoom=RADIUS_ZOOMS[self.near.radius],
            radius=self.near.radius,
        )

    def radius_url(self, miles):
        params = self.request.GET.copy()
        params['radius'] = miles
        return f'{self.request.path}?{params.urlencode()}'

    def get_context_data(self, **kwargs):
        label = (self.request.GET.get('label') or f'{self.near.lat:.3f}, {self.near.lng:.3f}')[:MAX_LABEL]
        return super().get_context_data(
            title=f'Within {self.near.radius} mile{"s" if self.near.radius != 1 else ""} of {label}',
            kind='Near me',
            population=None,
            context_bar=None,
            radius_options=[
                {'miles': miles, 'url': self.radius_url(miles), 'current': miles == self.near.radius}
                for miles in RADIUS_CHOICES
            ],
            privacy_note=True,
            **kwargs,
        )
```

`Home.get_context_data` gains:

```python
            find_area_places=find_area_places(),
            find_area_counties=[p for p in find_area_places() if p['type'] == Region.Type.COUNTY],
            focus_find=self.request.GET.get('find') == '1',
            maptiler_key=settings.MAPTILER_API_KEY,
```

- [ ] **Step 7: Templates**

`camp/templates/emissions/includes/find-area.html` is the pesticides include with the emissions near-me URL:

```django
<section class="box find-area" id="find" data-maptiler-key="{{ maptiler_key }}" data-near-url="{% url 'emissions:near-me' %}" data-year="{{ year }}">
    <h2 class="title is-5">Find your area</h2>
    <div class="field has-addons">
        <div class="control is-expanded has-icons-left">
            <input class="input" type="search" id="find-area-query" placeholder="Search a city, ZIP, county, or address" autocomplete="off" aria-label="Search a city, ZIP, county, or address" role="combobox" aria-autocomplete="list" aria-expanded="false" aria-controls="find-area-results"{% if focus_find %} autofocus{% endif %}>
            <span class="icon is-left"><span class="fa-regular fa-magnifying-glass"></span></span>
        </div>
        <div class="control"><button type="button" class="button is-primary" id="find-area-locate"><span class="icon"><span class="fa-regular fa-location-crosshairs"></span></span><span>Use my location</span></button></div>
    </div>
    <ul class="find-area-results" id="find-area-results" role="listbox" hidden></ul>
    <p class="help" id="find-area-status"></p>
    {% if find_area_counties %}
        <p class="find-area-counties">
            <span class="has-text-grey">Or jump to a county:</span>
            {% for county in find_area_counties %}<a href="{{ county.url }}{{ scope_qs }}">{{ county.short_name }}</a>{% if not forloop.last %}<span class="find-area-sep" aria-hidden="true">·</span>{% endif %}{% endfor %}
        </p>
    {% endif %}
    <p class="is-size-7 has-text-grey">Address searches are sent to MapTiler; place names are matched here in your browser. We don't store locations.</p>
    {{ find_area_places|json_script:"find-area-places" }}
</section>
```

In `emissions/home.html`, insert `{% include 'emissions/includes/find-area.html' %}` directly before `{% if context_bar %}`. In `emissions/base.html`, add `<script src="{% static 'js/pesticides/find-area.js' %}"></script>` before `explorer.js`; its `htmx:load` handler already calls `PesticidesFindArea.init(root)`.

`camp/templates/emissions/area.html`:

```django
{% extends 'emissions/base.html' %}
{% load humanize emissions_explorer %}

{% block title %}{{ title }} | {{ block.super }}{% endblock %}
{% block breadcrumb-list %}{% if county_region and county_region != area.region %}<li><a href="{{ county_region.get_emissions_url }}{{ scope_qs }}">{{ county_region.name }}</a></li>{% endif %}<li class="is-active"><a aria-current="page">{{ title }}</a></li>{% endblock %}

{% block explorer-content %}
<div class="content">
    <p class="heading mb-1">{{ kind }}{% if county_region and county_region != area.region %} · {{ county_region.name }}{% endif %}{% if population %} · {{ population|intcomma }} people{% endif %}</p>
    <h1 class="title is-3">{{ title }}</h1>
    {% if radius_options %}
    <div class="buttons has-addons">
        {% for option in radius_options %}<a class="button is-small{% if option.current %} is-link is-selected{% endif %}" href="{{ option.url }}">{{ option.miles }} mi</a>{% endfor %}
    </div>
    {% endif %}
</div>

<div class="columns is-multiline has-text-centered">
    <div class="column"><p class="heading">Facilities in {{ year }}</p><p class="title">{{ totals.facilities }}</p></div>
    <div class="column"><p class="heading">{{ pollutant.name }}</p><p class="title">{{ total|amount:pollutant }} <span class="is-size-5">{{ pollutant.unit }}/yr</span></p></div>
    <div class="column"><p class="heading">Per square mile</p><p class="title">{{ per_sq_mi|amount:pollutant }} <span class="is-size-5">{{ pollutant.unit }}/yr</span></p></div>
    {% if county_share is not None and county_region != area.region %}
    <div class="column"><p class="heading">Share of {{ county_region.name }}</p><p class="title">{{ county_share|percent }}</p></div>
    {% endif %}
</div>

{% include 'emissions/includes/facility-map.html' %}

{% if context_bar %}{% include 'emissions/includes/context-bar.html' %}{% endif %}

<h2 class="title is-4 mt-5">Top facilities</h2>
{% if top_rows %}
{% include 'emissions/includes/facility-table.html' with rows=top_rows sortable=False %}
{% else %}
<p class="has-text-grey">No facilities here reported {{ pollutant.name }} in {{ year }}.</p>
{% endif %}

<div class="columns mt-5">
    <div class="column">
        <h2 class="title is-4">By sector</h2>
        {% include 'emissions/includes/sector-rows.html' with rows=top_sectors %}
    </div>
    <div class="column">
        {% emissions_trend_chart by_year pollutant year %}
    </div>
</div>
{% if privacy_note %}<p class="is-size-7 has-text-grey">This page's location is only in its address; we don't store it.</p>{% endif %}
{% endblock %}
```

`area.region` exists on `RegionArea` only. On near-me `area.region` is an empty template variable, so the `!=` comparisons fall through to showing the county. That's intended: near-me has no region of its own.

- [ ] **Step 8: Run the tests**

Run: `$TEST camp/apps/emissions camp/apps/regions`
Expected: all PASS.

- [ ] **Step 9: Look at it**

Open these on the 8003 server (hard refresh), and check each renders with the map framed where you'd expect. The outline mask and Areas switch arrive in Task 8.
- `/tools/emissions/`: the find box works for "Fresno", "93725" and an address.
- A county page and a ZIP page.
- A near-me page from "Use my location" or an address.

- [ ] **Step 10: Commit**

```bash
git -C <worktree> add camp/apps/regions/models.py camp/apps/emissions/views.py camp/apps/emissions/urls.py \
  camp/templates/emissions/area.html camp/templates/emissions/includes/find-area.html \
  camp/templates/emissions/home.html camp/templates/emissions/base.html camp/apps/emissions/tests/test_areas_pages.py
git -C <worktree> commit -m "feat(emissions): region pages, near-me and find-your-area"
```

---

### Task 7: The facility page's "Area" line

**Files:**
- Modify: `camp/apps/emissions/views.py` (`FacilityDetail.get_context_data`, plus a small `area_links()` helper)
- Modify: `camp/templates/emissions/facility-detail.html` (the address line, and the new Area line under it)
- Test: `camp/apps/emissions/tests/test_areas_pages.py`

**Interfaces:**
- Consumes: `areas.facility_areas(facility)` (Task 4), `Region.get_emissions_url()` and `views.region_title()` (Task 6).
- Produces: `views.area_links(regions) -> [{'label', 'url'}]`. Context `area_links` on the facility page.

- [ ] **Step 1: Write the failing tests**

Append to `camp/apps/emissions/tests/test_areas_pages.py`:

```python
class FacilityAreaLineTests(TestCase):
    fixtures = ['regions.yaml', 'emissions.yaml']

    def setUp(self):
        cache.clear()

    def test_area_links_from_the_point_beside_the_reported_address(self):
        from camp.apps.emissions.models import Facility

        plant = Facility.objects.get(name='TEST PLANT')
        tract = make(Region.Type.TRACT, '06019000100', AROUND_PLANT)
        tract.metadata = {**tract.metadata, 'namelsad': 'Census Tract 1'}
        tract.save(update_fields=['metadata'])
        content = self.client.get(plant.get_absolute_url()).content.decode()
        # The address as the state reported it, ZIP included...
        assert '93728' in content
        # ...and the areas the facility counts in, from its point.
        assert f'href="{plant.county.get_emissions_url()}' in content
        assert f'href="{tract.get_emissions_url()}' in content and 'Census Tract 1' in content

    def test_no_point_links_the_county_only(self):
        from camp.apps.emissions.models import Facility

        cement = Facility.objects.get(name='TEST CEMENT')
        cement.point = None
        cement.save(update_fields=['point'])
        links = views.area_links([cement.county])
        assert [link['url'] for link in links] == [cement.county.get_emissions_url()]
```

- [ ] **Step 2: Run them to verify they fail**

Run: `$TEST camp/apps/emissions/tests/test_areas_pages.py -k FacilityArea`
Expected: FAIL (`AttributeError: module 'camp.apps.emissions.views' has no attribute 'area_links'`).

- [ ] **Step 3: Implement**

In `camp/apps/emissions/views.py`, add after `region_title`:

```python
def area_links(regions):
    """The facility page's "Area" line: each region it counts in, labelled, linking to its page."""
    labels = {Region.Type.ZIPCODE: 'ZIP {}'}
    return [{
        'label': labels.get(region.type, '{}').format(region_title(region)),
        'url': region.get_emissions_url(),
    } for region in regions]
```

In `FacilityDetail.get_context_data`, add `area_links=area_links(areas.facility_areas(facility)),` to the `super().get_context_data(...)` call.

In `camp/templates/emissions/facility-detail.html`, replace line 13's `<p>…</p>`, the address line, with:

```django
    <p>{{ facility.address.street|title }}, {% if facility.city %}{{ facility.city.name }}{% else %}{{ facility.address.city|title }}{% endif %}{% if facility.address.zipcode %} {{ facility.address.zipcode }}{% endif %} · {{ facility.county.name }}</p>
    {% if area_links %}
    {# From the facility's location on the map, which can differ from its reported address (the state's data, shown as given). #}
    <p class="facility-areas is-size-7">Counted in: {% for link in area_links %}<a href="{{ link.url }}{{ scope_qs }}">{{ link.label }}</a>{% if not forloop.last %} · {% endif %}{% endfor %}
        <span class="has-text-grey">(by its location on the map)</span></p>
    {% endif %}
```

- [ ] **Step 4: Run the tests**

Run: `$TEST camp/apps/emissions`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git -C <worktree> add camp/apps/emissions/views.py camp/templates/emissions/facility-detail.html camp/apps/emissions/tests/test_areas_pages.py
git -C <worktree> commit -m "feat(emissions): facility pages link the county, ZIP area and tract the facility counts in"
```

---

### Task 8: The Areas view on the map

**Files:**
- Rewrite: `assets/js/emissions/facility-map.js` (the full file is below)
- Rewrite: `camp/templates/emissions/includes/map-toolbar.html`
- Modify: `camp/apps/emissions/views.py` (`facility_map_config`: toolbar on compact Areas maps, and the level and measure options for the toolbar)
- Modify: `assets/css/emissions/facility-map.css`
- Modify: `scripts/emissions_map_smoke.py`
- Test: `camp/apps/emissions/tests/test_views.py` (`MapTests`)

**Interfaces:**
- Consumes the data attributes from Task 6:
  - `areas`, `areas-url`, `shapes-url`, `region-url`
  - `view`, `level`, `measure`
  - `outline-url`, `radius`, `center`
- Consumes the endpoints from Tasks 2 and 5:
  - `…/regions/geojson/?type=<level>&simplify=1`
  - `…/emissions/areas/?level=<level>&<query>`
  - the region detail JSON: `{data: {boundary: {geometry}}}`
- Produces:
  - Toolbar markup: `[data-view]` buttons, `.facility-map-level [data-level]`, `.facility-map-measure [data-measure]`. The level and measure dropdowns carry `data-areas-only`.
  - The container flag `data-areas-loaded="1"` once area values are drawn (for the smoke script).
  - The module instance fields `view`, `level`, `measure` (for the smoke script).

- [ ] **Step 1: Write the failing tests**

Add to `MapTests` in `camp/apps/emissions/tests/test_views.py`:

```python
    def test_map_page_has_the_areas_controls(self):
        content = self.get('map', params={'view': 'areas', 'level': 'tract'}).content.decode()
        assert 'data-view="facilities"' in content and 'data-view="areas"' in content
        assert 'data-level="tract"' in content and 'data-measure="per_resident"' in content
        assert 'data-areas="1"' in content

    def test_region_pages_have_the_switch_but_no_sector_filter(self):
        fresno = Region.objects.get(type=Region.Type.COUNTY, slug='fresno')
        content = self.client.get(fresno.get_emissions_url()).content.decode()
        assert 'data-view="areas"' in content
        assert 'facility-map-sector' not in content

    def test_facility_pages_have_no_areas_controls(self):
        content = self.client.get(self.plant.get_absolute_url()).content.decode()
        assert 'data-view="areas"' not in content
```

- [ ] **Step 2: Run them to verify they fail**

Run: `$TEST camp/apps/emissions/tests/test_views.py -k "areas_controls or switch_but or no_areas"`
Expected: FAIL. The toolbar has no view controls, and compact maps have no toolbar.

- [ ] **Step 3: Map config**

In `facility_map_config`:
- Add the template-only options to `config`:

```python
        'level_options': [(level, label) for level, label in (
            (Region.Type.COUNTY, 'Counties'), (Region.Type.ZIPCODE, 'ZIP areas'), (Region.Type.TRACT, 'Census tracts'))],
        'measure_options': [('density', 'Per square mile'), ('total', 'Total'), ('per_resident', 'Per 1,000 residents')],
```

- Extend `template_only` to `{'sector', 'sector_label', 'level_options', 'measure_options'}`.
- Change the `toolbar_template=` argument to

```python
        toolbar_template='emissions/includes/map-toolbar.html' if mode == 'full' or areas_view else None,
```

- [ ] **Step 4: The toolbar template**

Replace `camp/templates/emissions/includes/map-toolbar.html`:

```django
{% comment %}
The facility map's own toolbar controls (facility-map.js binds them):
the Facilities | Areas switch and, in Areas, the level and measure; the
sector filter on the full map only.
{% endcomment %}
<div class="map-toolbar-filters" role="group" aria-label="Map filters">
    {% if map_config.areas %}
    <div class="buttons has-addons facility-map-view" role="group" aria-label="Show">
        <button type="button" class="button{% if map_config.view != 'areas' %} is-selected is-link{% endif %}" data-view="facilities" aria-pressed="{% if map_config.view != 'areas' %}true{% else %}false{% endif %}">Facilities</button>
        <button type="button" class="button{% if map_config.view == 'areas' %} is-selected is-link{% endif %}" data-view="areas" aria-pressed="{% if map_config.view == 'areas' %}true{% else %}false{% endif %}">Areas</button>
    </div>
    <div class="dropdown map-toolbar-dropdown facility-map-level" data-areas-only{% if map_config.view != 'areas' %} hidden{% endif %}>
        <div class="dropdown-trigger">
            <button type="button" class="button" aria-haspopup="true" aria-expanded="false">
                <span class="map-toolbar-label">{% for value, label in map_config.level_options %}{% if value == map_config.level %}{{ label }}{% endif %}{% endfor %}</span>
                <span class="icon is-small"><span class="fa-regular fa-chevron-down" aria-hidden="true"></span></span>
            </button>
        </div>
        <div class="dropdown-menu" role="menu"><div class="dropdown-content">
            {% for value, label in map_config.level_options %}<a href="#" class="dropdown-item{% if value == map_config.level %} is-active{% endif %}" data-level="{{ value }}">{{ label }}</a>{% endfor %}
        </div></div>
    </div>
    <div class="dropdown map-toolbar-dropdown facility-map-measure" data-areas-only{% if map_config.view != 'areas' %} hidden{% endif %}>
        <div class="dropdown-trigger">
            <button type="button" class="button" aria-haspopup="true" aria-expanded="false">
                <span class="map-toolbar-label">{% for value, label in map_config.measure_options %}{% if value == map_config.measure %}{{ label }}{% endif %}{% endfor %}</span>
                <span class="icon is-small"><span class="fa-regular fa-chevron-down" aria-hidden="true"></span></span>
            </button>
        </div>
        <div class="dropdown-menu" role="menu"><div class="dropdown-content">
            {% for value, label in map_config.measure_options %}<a href="#" class="dropdown-item{% if value == map_config.measure %} is-active{% endif %}" data-measure="{{ value }}">{{ label }}</a>{% endfor %}
        </div></div>
    </div>
    {% endif %}
    {% if map_config.mode == 'full' %}
    {# The sector filter narrows the map without a page swap. #}
    <div class="dropdown map-toolbar-dropdown facility-map-sector{% if map_config.sector %} is-set{% endif %}">
        <div class="dropdown-trigger">
            <button type="button" class="button" aria-haspopup="true" aria-expanded="false">
                <span class="icon"><span class="fa-duotone fa-fw fa-layer-group explorer-icon" aria-hidden="true"></span></span>
                <span class="map-toolbar-label">{{ map_config.sector_label|default:"All sectors" }}</span>
                <span class="icon is-small"><span class="fa-regular fa-chevron-down" aria-hidden="true"></span></span>
            </button>
        </div>
        <div class="dropdown-menu" role="menu">
            <div class="dropdown-content">
                <a href="#" class="dropdown-item{% if not map_config.sector %} is-active{% endif %}" data-sector="">All sectors</a>
                <hr class="dropdown-divider">
                {% for value, label in sector_options %}
                <a href="#" class="dropdown-item{% if map_config.sector == value %} is-active{% endif %}" data-sector="{{ value }}">{{ label }}</a>
                {% endfor %}
            </div>
        </div>
    </div>
    {% endif %}
</div>
```

The existing `test_compact_maps_have_no_sector_filter` (sector page) keeps passing: sector pages have no Areas view, so no toolbar.

- [ ] **Step 5: `facility-map.js`**

Replace the whole file with:

```js
/*
 * Facility map for the Facility Emissions Explorer, a module on the map core
 * (assets/js/maps/), registered as 'facility'.
 *
 * Two views, one at a time:
 *   Facilities  one circle per permitted facility: area scaled by the
 *               selected pollutant (square root, so the largest emitter
 *               doesn't bury the rest), colour by a fixed log-scale class;
 *               facilities that reported none are small hollow grey rings.
 *   Areas       counties, ZIP areas or 2020 census tracts shaded by the
 *               facilities inside them: per square mile, total, or per
 *               1,000 residents (fixed log-scale classes). Shapes come from
 *               the regions GeoJSON (simplified together, so shared borders
 *               stay shared), numbers from /api/2.0/emissions/areas/.
 *
 * County and air district outlines sit under the data, and everything draws
 * over the whole basemap, labels included. On a region or near-me page the
 * page's own area is outlined and everything outside it washed out.
 * Config comes from the container's data-* attributes
 * (views.facility_map_config); the chrome is the core's.
 */
(function () {
  'use strict';

  var M = window.SJVAirMaps;
  if (!M || !M.register) return;

  // ColorBrewer Blues, one colour per class below (the pesticides map's
  // default ramp, without its palest step, which vanishes on the basemap).
  var RAMP = ['#c6dbef', '#9ecae1', '#6baed6', '#3182bd', '#08519c'];
  // Fixed classes on a log scale, per display unit: stable across pollutants,
  // counties and years, and readable ("1-10 tons"). Toxics are shown in lbs.
  var CLASS_BREAKS = { tons: [0.1, 1, 10, 100], lbs: [1, 10, 100, 1000] };
  // The Areas view's classes, per measure and unit.
  var AREA_BREAKS = {
    density: { tons: [0.01, 0.1, 1, 10], lbs: [0.1, 1, 10, 100] },
    total: { tons: [1, 10, 100, 1000], lbs: [10, 100, 1000, 10000] },
    per_resident: { tons: [0.1, 1, 10, 100], lbs: [1, 10, 100, 1000] },
  };
  var AREA_FIELDS = { density: 'per_sq_mi', total: 'total', per_resident: 'per_1k_residents' };
  var AREA_SUFFIX = { density: ' per sq mi', total: '', per_resident: ' per 1,000 people' };
  var LEVEL_NAMES = { county: '', zipcode: 'ZIP ', tract: 'Tract ' };
  var EMPTY_COLOR = '#8a94a3';
  var HIGHLIGHT_COLOR = '#d35400';
  var COUNTY_COLOR = '#1f2d3d';
  var DISTRICT_COLOR = '#6a3d9a';
  var MIN_RADIUS = 3;
  var MAX_RADIUS = 26;
  var WORLD_RING = [[-180, -85], [180, -85], [180, 85], [-180, 85], [-180, -85]];
  var CIRCLE_POINTS = 64;
  var METERS_PER_MILE = 1609.344;

  var escapeHtml = M.escapeHtml;
  var logError = M.logger('facility-map');

  // The same rules as the `amount` template filter.
  function amount(value) {
    if (value === null || value === undefined) return '—';
    var size = Math.abs(value);
    if (size && size < 0.01) return '<0.01';
    var digits = size && size < 1 ? 2 : (size && size < 10 ? 1 : 0);
    return value.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits });
  }

  function breaksFor(unit) {
    return CLASS_BREAKS[unit] || CLASS_BREAKS.tons;
  }

  function areaBreaksFor(measure, unit) {
    var set = AREA_BREAKS[measure] || AREA_BREAKS.density;
    return set[unit] || set.tons;
  }

  function classIndex(value, breaks) {
    var index = 0;
    while (index < breaks.length && value >= breaks[index]) index++;
    return index;
  }

  // "under 0.1", "0.1–1", ..., "100 and up"
  function classLabel(index, breaks) {
    if (index === 0) return 'under ' + amount(breaks[0]);
    if (index === breaks.length) return amount(breaks[index - 1]) + ' and up';
    return amount(breaks[index - 1]) + '–' + amount(breaks[index]);
  }

  function radiusFor(value, max) {
    return MIN_RADIUS + (MAX_RADIUS - MIN_RADIUS) * Math.sqrt(value / max);
  }

  function getJson(url) {
    return fetch(url, { credentials: 'same-origin' }).then(function (response) {
      if (!response.ok) throw new Error('HTTP ' + response.status);
      return response.json();
    });
  }

  // Precompute each circle so the layer's paint is plain `get`s.
  function prepare(collection, unit) {
    var features = collection.features || [];
    var positive = features.map(function (f) { return f.properties.value; }).filter(function (v) { return v > 0; });
    var max = positive.length ? Math.max.apply(null, positive) : 0;
    var breaks = breaksFor(unit);
    features.forEach(function (feature) {
      var p = feature.properties;
      var reported = p.value > 0 && max > 0;
      p._radius = reported ? radiusFor(p.value, max) : MIN_RADIUS;
      p._color = reported ? RAMP[classIndex(p.value, breaks)] : EMPTY_COLOR;
      p._empty = reported ? 0 : 1;
      p._sort = reported ? p.value : 0;
    });
    return { collection: collection, breaks: breaks, max: max };
  }

  // Everything outside `geometry` (a Polygon or MultiPolygon), as one polygon
  // with the geometry's outer rings as holes: the page's area stays clear,
  // the rest is washed out.
  function maskFor(geometry) {
    var rings = [];
    if (geometry.type === 'Polygon') rings = [geometry.coordinates[0]];
    if (geometry.type === 'MultiPolygon') rings = geometry.coordinates.map(function (part) { return part[0]; });
    if (!rings.length) return M.EMPTY;
    return { type: 'Feature', properties: {}, geometry: { type: 'Polygon', coordinates: [WORLD_RING].concat(rings) } };
  }

  // A `miles` circle around [lng, lat] as a polygon (the SDK has no circles in metres).
  function circle(center, miles) {
    var meters = miles * METERS_PER_MILE;
    var dLat = meters / 111320;
    var dLng = meters / (111320 * Math.cos(center[1] * Math.PI / 180));
    var ring = [];
    for (var i = 0; i <= CIRCLE_POINTS; i++) {
      var angle = (i % CIRCLE_POINTS) * 2 * Math.PI / CIRCLE_POINTS;
      ring.push([center[0] + dLng * Math.cos(angle), center[1] + dLat * Math.sin(angle)]);
    }
    return { type: 'Polygon', coordinates: [ring] };
  }

  function FacilityMap(shell) {
    var self = this;
    this.shell = shell;
    this.el = shell.el;
    // The container's live dataset (an adopt rewrites this same element's).
    this.data = shell.data;
    this.map = shell.map;
    this.popup = null;
    this.fitted = false;
    this.legendData = null;
    // The Areas view: shapes per level (they never change with the scope),
    // the current values, and a request counter of its own (the shell's
    // ticket is the facilities fetch's).
    this.shapes = {};
    this.areaData = null;
    this.areaRequest = 0;
    this.outlineBounds = null;
    this.readViewState();
    // Layer-bound listeners wait for their layer, so they're bound once here
    // rather than on every style load.
    this.map.on('click', 'facilities', function (evt) { self.openPopup(evt.features[0], evt.lngLat); });
    this.map.on('click', 'areas-fill', function (evt) { self.openAreaPopup(evt.features[0], evt.lngLat); });
    ['facilities', 'areas-fill'].forEach(function (layer) {
      self.map.on('mouseenter', layer, function () { self.map.getCanvas().style.cursor = 'pointer'; });
      self.map.on('mouseleave', layer, function () { self.map.getCanvas().style.cursor = ''; });
    });
    // The scope bar's links (year, pollutant, toggles) were rendered before
    // the reader switched view or sector here; carry the map's state along on
    // the boosted request so the next page opens the same way.
    this.onConfigRequest = function (event) {
      var elt = event.detail && event.detail.elt;
      if (!elt || !elt.closest || !elt.closest('.explorer-scope')) return;
      var params = event.detail.parameters;
      var sector = new URLSearchParams(self.data.query || '').get('sector');
      if (sector) params.sector = sector;
      if (self.view !== 'areas') return;
      params.view = 'areas';
      params.level = self.level;
      params.measure = self.measure;
    };
    document.body.addEventListener('htmx:configRequest', this.onConfigRequest);
    // For debugging from the console: document.querySelector('.facility-map').facilityMap
    this.el.facilityMap = this;
  }

  FacilityMap.prototype.readViewState = function () {
    this.areasEnabled = this.data.areas === '1';
    this.view = this.areasEnabled && this.data.view === 'areas' ? 'areas' : 'facilities';
    this.level = this.data.level || 'zipcode';
    this.measure = this.data.measure || 'density';
  };

  // Bottom to top: the shaded areas, the wash outside the page's area, the
  // county and district lines, the facilities, the page's area outline. On
  // top of the whole basemap, labels included: the data is what the map is for.
  FacilityMap.prototype.addLayers = function () {
    this.shell.ensureSource('areas');
    this.shell.ensureSource('outline');
    this.shell.ensureSource('outline-mask');
    this.shell.ensureSource('counties', { data: this.data.countiesUrl || M.EMPTY });
    this.shell.ensureSource('districts', { data: this.data.districtsUrl || M.EMPTY });
    this.shell.ensureSource('facilities');
    this.shell.ensureLayer({
      id: 'areas-fill', type: 'fill', source: 'areas',
      paint: { 'fill-color': ['get', '_color'], 'fill-opacity': ['case', ['==', ['get', '_empty'], 1], 0, 0.72] },
    });
    this.shell.ensureLayer({
      id: 'areas-line', type: 'line', source: 'areas',
      paint: { 'line-color': '#4a5568', 'line-width': 0.5, 'line-opacity': 0.5 },
    });
    this.shell.ensureLayer({
      id: 'outline-mask', type: 'fill', source: 'outline-mask',
      paint: { 'fill-color': '#ffffff', 'fill-opacity': 0.55 },
    });
    this.shell.ensureLayer({
      id: 'counties', type: 'line', source: 'counties',
      paint: { 'line-color': COUNTY_COLOR, 'line-width': 1, 'line-opacity': 0.5 },
    });
    this.shell.ensureLayer({
      id: 'districts', type: 'line', source: 'districts',
      paint: { 'line-color': DISTRICT_COLOR, 'line-width': 2, 'line-dasharray': [3, 2] },
    });
    this.shell.ensureLayer({
      id: 'facilities', type: 'circle', source: 'facilities',
      // Larger values draw on top.
      layout: { 'circle-sort-key': ['get', '_sort'] },
      paint: { 'circle-radius': ['get', '_radius'], 'circle-color': ['get', '_color'] },
    });
    this.shell.ensureLayer({
      id: 'outline-line', type: 'line', source: 'outline',
      layout: { 'line-join': 'round' },
      paint: { 'line-color': HIGHLIGHT_COLOR, 'line-width': 2.5, 'line-opacity': 0.9 },
    });
    this.applyHighlight();
    this.applyView();
  };

  // Hollow rings for "none reported"; with a highlighted facility (a facility
  // page), it gets an orange ring and everything else fades.
  FacilityMap.prototype.applyHighlight = function () {
    if (!this.map || !this.map.getLayer('facilities')) return;
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

  // One view at a time: the layers, the toolbar's switch and its Areas-only
  // controls follow `this.view`.
  FacilityMap.prototype.applyView = function () {
    var areas = this.view === 'areas';
    if (this.map) {
      var set = function (map, id, visible) {
        if (map.getLayer(id)) map.setLayoutProperty(id, 'visibility', visible ? 'visible' : 'none');
      };
      set(this.map, 'facilities', !areas);
      set(this.map, 'areas-fill', areas);
      set(this.map, 'areas-line', areas);
    }
    var wrap = this.shell.wrap;
    if (!wrap) return;
    Array.prototype.forEach.call(wrap.querySelectorAll('[data-view]'), function (button) {
      var on = button.getAttribute('data-view') === (areas ? 'areas' : 'facilities');
      button.classList.toggle('is-selected', on);
      button.classList.toggle('is-link', on);
      button.setAttribute('aria-pressed', on ? 'true' : 'false');
    });
    Array.prototype.forEach.call(wrap.querySelectorAll('[data-areas-only]'), function (control) {
      control.hidden = !areas;
    });
  };

  FacilityMap.prototype.url = function () {
    var query = this.data.query || '';
    return this.data.geojsonUrl + (query ? '?' + query : '');
  };

  // The facilities always load (switching back to them is then instant);
  // the areas load when they're the view.
  FacilityMap.prototype.load = function () {
    this.loadFacilities();
    if (this.view === 'areas') this.loadAreas();
    this.loadOutline();
  };

  FacilityMap.prototype.loadFacilities = function () {
    var self = this;
    var ticket = this.shell.ticket();
    this.el.dataset.loaded = '';
    this.shell.setStatus('Loading facilities…');
    getJson(this.url())
      .then(function (collection) {
        // A newer request (a sector change, a swap) or a destroy superseded this one.
        if (!self.shell.isCurrent(ticket)) return;
        self.show(collection);
      })
      .catch(function (err) {
        if (!self.shell.isCurrent(ticket)) return;
        self.shell.setStatus('Couldn\'t load the facilities');
        logError('failed to load facilities', err);
      });
  };

  FacilityMap.prototype.show = function (collection) {
    var prepared = prepare(collection, this.data.unit);
    this.legendData = prepared;
    this.shell.setSourceData('facilities', prepared.collection);
    this.applyHighlight();
    this.shell.updateLegend();
    if (this.view === 'facilities') this.shell.setStatus('');
    if (!this.fitted) {
      this.fit(prepared.collection);
      this.fitted = true;
    }
    this.el.dataset.loaded = '1';
  };

  FacilityMap.prototype.areasUrl = function () {
    var params = new URLSearchParams(this.data.query || '');
    params.set('level', this.level);
    return this.data.areasUrl + '?' + params.toString();
  };

  FacilityMap.prototype.shapesFor = function (level) {
    var self = this;
    if (this.shapes[level]) return Promise.resolve(this.shapes[level]);
    return getJson(this.data.shapesUrl + '?type=' + encodeURIComponent(level) + '&simplify=1').then(function (shapes) {
      self.shapes[level] = shapes;
      return shapes;
    });
  };

  FacilityMap.prototype.loadAreas = function () {
    var self = this;
    var request = ++this.areaRequest;
    var level = this.level;
    this.el.dataset.areasLoaded = '';
    this.shell.setStatus('Loading areas…');
    Promise.all([this.shapesFor(level), getJson(this.areasUrl())])
      .then(function (results) {
        if (request !== self.areaRequest || !self.map) return;
        self.areaData = { level: level, shapes: results[0], values: results[1] };
        self.showAreas();
      })
      .catch(function (err) {
        if (request !== self.areaRequest || !self.map) return;
        self.shell.setStatus('Couldn\'t load the areas');
        logError('failed to load areas', err);
      });
  };

  // Joins the values to the shapes and colours them by the current measure
  // (a measure change re-runs this without fetching).
  FacilityMap.prototype.showAreas = function () {
    var data = this.areaData;
    if (!data) return;
    var byId = {};
    data.values.areas.forEach(function (area) { byId[area.id] = area; });
    var field = AREA_FIELDS[this.measure] || AREA_FIELDS.density;
    var breaks = areaBreaksFor(this.measure, data.values.unit);
    var features = (data.shapes.features || []).map(function (feature) {
      var area = byId[feature.id];
      var value = area ? area[field] : null;
      var shaded = value !== null && value !== undefined && value > 0;
      return {
        type: 'Feature',
        id: feature.id,
        geometry: feature.geometry,
        properties: Object.assign({}, feature.properties, {
          facilities: area ? area.facilities : 0,
          total: area ? area.total : null,
          per_sq_mi: area ? area.per_sq_mi : null,
          per_1k_residents: area ? area.per_1k_residents : null,
          _color: shaded ? RAMP[classIndex(value, breaks)] : EMPTY_COLOR,
          _empty: shaded ? 0 : 1,
        }),
      };
    });
    data.breaks = breaks;
    this.shell.setSourceData('areas', { type: 'FeatureCollection', features: features });
    this.shell.updateLegend();
    this.shell.setStatus('');
    this.el.dataset.areasLoaded = '1';
  };

  // The page's own area: a region's boundary (region pages) or the radius
  // (near-me), outlined, with everything outside washed out, and framed.
  FacilityMap.prototype.loadOutline = function () {
    var self = this;
    var center = M.parseCenter(this.data.center);
    var radius = parseFloat(this.data.radius);
    if (center && radius > 0) {
      this.showOutline(circle(center, radius));
      return;
    }
    if (!this.data.outlineUrl) {
      this.showOutline(null);
      return;
    }
    getJson(this.data.outlineUrl)
      .then(function (json) {
        var boundary = json && json.data && json.data.boundary;
        if (self.map) self.showOutline(boundary ? boundary.geometry : null);
      })
      .catch(function (err) { logError('failed to load the outline', err); });
  };

  FacilityMap.prototype.showOutline = function (geometry) {
    if (!geometry) {
      this.outlineBounds = null;
      this.shell.setSourceData('outline', M.EMPTY);
      this.shell.setSourceData('outline-mask', M.EMPTY);
      return;
    }
    this.shell.setSourceData('outline', { type: 'Feature', properties: {}, geometry: geometry });
    this.shell.setSourceData('outline-mask', maskFor(geometry));
    this.outlineBounds = M.geometryBounds(geometry);
    if (this.outlineBounds) this.map.fitBounds(this.outlineBounds, { padding: 24, duration: 0 });
  };

  // Home goes back to the page's area when it has one.
  FacilityMap.prototype.home = function () {
    return this.outlineBounds ? { bounds: this.outlineBounds, padding: 24 } : null;
  };

  // Frame the facilities, unless the page framed the map itself (a facility
  // page's centre, the covered counties' bounds, or the page's area).
  FacilityMap.prototype.fit = function (collection) {
    if (M.parseCenter(this.data.center) || M.parseBounds(this.data.bounds) || this.data.outlineUrl) return;
    var features = collection.features || [];
    if (!features.length) return;
    var bounds = new maptilersdk.LngLatBounds();
    features.forEach(function (f) { bounds.extend(f.geometry.coordinates); });
    this.map.fitBounds(bounds, { padding: 40, maxZoom: 12, duration: 0 });
  };

  FacilityMap.prototype.facilityUrl = function (id) {
    var url = (this.data.facilityUrl || '').replace('{id}', encodeURIComponent(id));
    var query = this.data.query || '';
    if (this.data.mode === 'compact') {
      var params = new URLSearchParams(query);
      params.delete('minor');
      query = params.toString();
    }
    return url + (query ? '?' + query : '');
  };

  FacilityMap.prototype.placePopup = function (html, lngLat) {
    var self = this;
    if (this.popup) this.popup.remove();
    this.popup = new maptilersdk.Popup({ maxWidth: this.shell.popupMaxWidth() }).setLngLat(lngLat).setHTML(html).addTo(this.map);
    // Clear of the toolbar and legend card, as on the pesticides map.
    this.shell.panPopupIntoView(this.popup);
    this.popup.on('close', function () { self.popup = null; });
    return this.popup;
  };

  FacilityMap.prototype.openPopup = function (feature, lngLat) {
    var p = feature.properties;
    var value = p._empty ? 'none reported' : amount(p.value) + ' ' + escapeHtml(this.data.unit) + '/yr';
    this.placePopup('<div class="facility-popup">' +
      '<p class="facility-popup-name"><a href="' + escapeHtml(this.facilityUrl(p.id)) + '">' + escapeHtml(p.name) + '</a></p>' +
      '<p>' + escapeHtml(p.sector) + '</p>' +
      '<p>' + escapeHtml(this.data.label) + ': <strong>' + value + '</strong>' + (p.rank ? ' · #' + p.rank : '') + '</p>' +
      '</div>', lngLat);
  };

  FacilityMap.prototype.openAreaPopup = function (feature, lngLat) {
    var self = this;
    var p = feature.properties;
    var unit = escapeHtml(this.data.unit);
    var name = (LEVEL_NAMES[this.level] || '') + p.name;
    var query = new URLSearchParams(this.data.query || '');
    query.delete('sector');
    var regionUrl = (this.data.regionUrl || '').replace('{id}', encodeURIComponent(p.id));
    var qs = query.toString();
    var line = function (label, value, suffix) {
      return '<p>' + label + ': <strong>' + (value === null || value === undefined ? '—' : amount(value) + ' ' + unit + '/yr' + suffix) + '</strong></p>';
    };
    var html = '<div class="facility-popup area-popup">' +
      '<p class="facility-popup-name">' + (regionUrl ? '<a href="' + escapeHtml(regionUrl + (qs ? '?' + qs : '')) + '">' + escapeHtml(name) + '</a>' : escapeHtml(name)) + '</p>' +
      '<p>' + p.facilities + ' facilit' + (p.facilities === 1 ? 'y' : 'ies') + ' · ' + escapeHtml(this.data.label) + '</p>' +
      line('Total', p.total, '') + line('Per square mile', p.per_sq_mi, '') + line('Per 1,000 residents', p.per_1k_residents, '') +
      (p.facilities ? '<p><button type="button" class="button is-small is-link is-light" data-show-facilities>Show facilities</button></p>' : '') +
      '</div>';
    var popup = this.placePopup(html, lngLat);
    var button = popup.getElement().querySelector('[data-show-facilities]');
    if (button) {
      button.addEventListener('click', function () {
        var shape = (self.areaData && self.areaData.shapes.features || []).filter(function (f) { return f.id === p.id; })[0];
        popup.remove();
        self.setView('facilities');
        var bounds = shape && M.geometryBounds(shape.geometry);
        if (bounds) self.map.fitBounds(bounds, { padding: 24, animate: !self.shell.reducedMotion });
      });
    }
  };

  // The legend card follows the view. It stays hidden until there's
  // something to put in it.
  FacilityMap.prototype.legend = function (body) {
    var legend = body.querySelector('.facility-map-legend');
    if (!legend) return;
    if (this.view === 'areas') {
      this.areaLegend(legend);
      return;
    }
    if (!this.legendData) return;
    if (this.shell.legendPanelEl) this.shell.legendPanelEl.hidden = false;
    var max = this.legendData.max;
    var breaks = this.legendData.breaks;
    var label = escapeHtml(this.data.label) + ' (' + escapeHtml(this.data.unit) + '/yr)';
    if (!max) {
      legend.innerHTML = '<p>No facilities here reported ' + escapeHtml(this.data.label) + '.</p>';
      return;
    }
    var sizes = [max, max / 10, max / 100].map(function (value) {
      var r = radiusFor(value, max);
      return '<span class="legend-size"><svg width="' + (2 * MAX_RADIUS + 2) + '" height="' + (2 * r + 2) + '">' +
        '<circle cx="' + (MAX_RADIUS + 1) + '" cy="' + (r + 1) + '" r="' + r + '"/></svg>' + amount(value) + '</span>';
    }).join('');
    var bins = '';
    for (var i = breaks.length; i >= 0; i--) {
      bins += '<span class="legend-bin"><span class="legend-swatch" style="background:' + RAMP[i] + '"></span>' +
        classLabel(i, breaks) + '</span>';
    }
    legend.innerHTML = '<p class="legend-title">' + label + '</p>' +
      '<div class="legend-sizes">' + sizes + '</div>' +
      '<div class="legend-bins">' + bins + '</div>' +
      '<p class="legend-empty"><span class="legend-ring"></span>None reported</p>';
  };

  FacilityMap.prototype.areaLegend = function (legend) {
    var data = this.areaData;
    if (!data || !data.breaks) return;
    if (this.shell.legendPanelEl) this.shell.legendPanelEl.hidden = false;
    var breaks = data.breaks;
    var title = escapeHtml(this.data.label) + ' (' + escapeHtml(data.values.unit) + '/yr' + (AREA_SUFFIX[this.measure] || '') + ')';
    var bins = '';
    for (var i = breaks.length; i >= 0; i--) {
      bins += '<span class="legend-bin"><span class="legend-swatch is-area" style="background:' + RAMP[i] + '"></span>' +
        classLabel(i, breaks) + '</span>';
    }
    var missing = data.values.facilities_without_point;
    legend.innerHTML = '<p class="legend-title">' + title + '</p>' +
      '<div class="legend-bins">' + bins + '</div>' +
      '<p class="legend-empty"><span class="legend-swatch is-area is-none"></span>No facilities' +
      (this.measure === 'per_resident' ? ' or no population' : '') + '</p>' +
      (missing ? '<p class="legend-note">' + missing + ' facilit' + (missing === 1 ? 'y has' : 'ies have') +
        ' no location and ' + (missing === 1 ? 'isn\'t' : 'aren\'t') + ' counted here.</p>' : '');
  };

  // The toolbar's controls: the view switch, level and measure (Areas), and
  // the sector filter (full map). The core runs the dropdowns themselves.
  FacilityMap.prototype.onChrome = function (wrap) {
    var self = this;
    if (this.shell.legendPanelEl && !this.legendData && !this.areaData) this.shell.legendPanelEl.hidden = true;
    var bind = function (selector, handler) {
      Array.prototype.forEach.call(wrap.querySelectorAll(selector), function (item) {
        if (item.getAttribute('data-bound')) return;
        item.setAttribute('data-bound', '1');
        item.addEventListener('click', function (event) {
          event.preventDefault();
          M.chrome.closeDropdowns(self.shell, null);
          handler(item);
        });
      });
    };
    bind('[data-sector]', function (item) { self.setSector(item.getAttribute('data-sector'), item.textContent.trim()); });
    bind('[data-view]', function (item) { self.setView(item.getAttribute('data-view')); });
    bind('[data-level]', function (item) { self.setLevel(item.getAttribute('data-level'), item.textContent.trim()); });
    bind('[data-measure]', function (item) { self.setMeasure(item.getAttribute('data-measure'), item.textContent.trim()); });
    this.applyView();
  };

  FacilityMap.prototype.onDropdownOpen = function () {
    if (this.popup) this.popup.remove();
  };

  // The address bar follows the view, level and measure (and the sector) so
  // a view can be shared; defaults are left out.
  FacilityMap.prototype.syncUrl = function () {
    var page = new URLSearchParams(window.location.search);
    if (this.view === 'areas') {
      page.set('view', 'areas');
      page.set('level', this.level);
      page.set('measure', this.measure);
    } else {
      page.delete('view');
      page.delete('level');
      page.delete('measure');
    }
    var search = page.toString();
    window.history.replaceState(window.history.state, '', window.location.pathname + (search ? '?' + search : ''));
  };

  FacilityMap.prototype.setView = function (view) {
    if (!this.areasEnabled) return;
    this.view = view === 'areas' ? 'areas' : 'facilities';
    this.applyView();
    this.syncUrl();
    if (this.view === 'areas' && (!this.areaData || this.areaData.level !== this.level)) {
      this.loadAreas();
    } else {
      this.shell.updateLegend();
    }
  };

  FacilityMap.prototype.setLevel = function (level, label) {
    this.level = level;
    this.markDropdown('.facility-map-level', '[data-level]', level, label);
    this.syncUrl();
    this.loadAreas();
  };

  FacilityMap.prototype.setMeasure = function (measure, label) {
    this.measure = measure;
    this.markDropdown('.facility-map-measure', '[data-measure]', measure, label);
    this.syncUrl();
    this.showAreas();
  };

  FacilityMap.prototype.markDropdown = function (selector, itemSelector, value, label) {
    var dropdown = this.shell.wrap && this.shell.wrap.querySelector(selector);
    if (!dropdown) return;
    var text = dropdown.querySelector('.map-toolbar-label');
    if (text && label) text.textContent = label;
    var attribute = itemSelector.slice(1, -1);
    Array.prototype.forEach.call(dropdown.querySelectorAll(itemSelector), function (item) {
      item.classList.toggle('is-active', item.getAttribute(attribute) === value);
    });
  };

  // The sector filter narrows both views without a page swap; the address
  // bar follows so the view can be shared.
  FacilityMap.prototype.setSector = function (sector, label) {
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
    var dropdown = this.shell.wrap && this.shell.wrap.querySelector('.facility-map-sector');
    if (dropdown) {
      dropdown.classList.toggle('is-set', !!sector);
      var text = dropdown.querySelector('.map-toolbar-label');
      if (text) text.textContent = label || 'All sectors';
      Array.prototype.forEach.call(dropdown.querySelectorAll('[data-sector]'), function (item) {
        item.classList.toggle('is-active', item.getAttribute('data-sector') === (sector || ''));
      });
    }
    this.loadFacilities();
    if (this.view === 'areas') this.loadAreas();
  };

  // A swap brought a new page: drop what belonged to the old one (its
  // popup, the located dot, its area values and outline), take the new
  // page's view, frame it, and reload.
  FacilityMap.prototype.onAdopt = function () {
    if (this.popup) this.popup.remove();
    // The new page's legend card waits for its own data, as on a first build.
    this.legendData = null;
    this.areaData = null;
    if (this.shell.legendPanelEl) this.shell.legendPanelEl.hidden = true;
    this.shell.setSourceData('locate', M.EMPTY);
    this.shell.setSourceData('areas', M.EMPTY);
    this.shell.setStatus('');
    this.readViewState();
    this.applyView();
    this.fitted = false;
    this.shell.frame();
    this.applyHighlight();
    this.load();
  };

  FacilityMap.prototype.destroy = function () {
    if (this.popup) this.popup.remove();
    document.body.removeEventListener('htmx:configRequest', this.onConfigRequest);
    this.map = null;
  };

  M.register('facility', {
    selector: '.facility-map',
    lifecycle: 'adopt',
    features: { controls: ['zoom', 'locate', 'home'], toolbar: true, legend: true, status: true, expand: true },
    // The key readers' folded legends were saved under before the core.
    panelStoragePrefix: 'emissions:facility-map:panel:',
    create: function (shell) { return new FacilityMap(shell); },
  });

  window.EmissionsFacilityMap = {
    init: M.init,
    instances: function () { return M.instances('facility'); },
  };
})();
```

Run: `node --check <worktree>/assets/js/emissions/facility-map.js`

- [ ] **Step 6: CSS**

Append to `assets/css/emissions/facility-map.css`:

```css
/* The Facilities | Areas switch. */
.facility-map-view.buttons {
  margin-bottom: 0;
}
.facility-map-view .button {
  height: 33px; /* the SDK's control buttons, as the other toolbar buttons */
  font-size: 0.85rem;
}

/* Area classes: square swatches, and an outline-only "no facilities". */
.facility-map-legend .legend-swatch.is-area {
  border-radius: 2px;
}
.facility-map-legend .legend-swatch.is-none {
  background: transparent;
  border: 1px solid #4a5568;
}
.facility-map-legend .legend-note {
  margin-top: 0.35rem;
  color: #7a7a7a;
  max-width: 14rem;
}
.area-popup p {
  margin: 0 0 0.2rem;
}
```

- [ ] **Step 7: Run the tests**

Run: `$TEST camp/apps/emissions camp/api/v2/emissions camp/api/v2/regions`
Expected: all PASS.

- [ ] **Step 8: Smoke checks**

In `scripts/emissions_map_smoke.py`:
- Add a helper after `feature_count`:

```python
def wait_areas(driver, timeout=MAP_TIMEOUT):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if driver.execute_script("var el = document.querySelector('.facility-map'); return !!el && el.dataset.areasLoaded === '1';"):
            return True
        time.sleep(0.25)
    return False


def area_count(driver):
    return driver.execute_script(
        "var m = window.EmissionsFacilityMap.instances()[0];"
        "return m ? m.map.querySourceFeatures('areas').filter(function (f) { return f.properties._empty === 0; }).length : 0;"
    )
```

- In `main()`, before `errors = console_errors(driver)`, add:

```python
        driver.get(args.base + '/tools/emissions/map/')
        wait_loaded(driver)
        driver.execute_script("document.querySelector('[data-view=areas]').click()")
        check(results, 'areas view shades ZIP areas', wait_areas(driver) and area_count(driver) > 0, f'{area_count(driver)} shaded')
        check(results, 'areas view hides the facilities', driver.execute_script(
            "var m = window.EmissionsFacilityMap.instances()[0]; return m.map.getLayoutProperty('facilities', 'visibility') === 'none';"))
        check(results, 'view is in the URL', 'view=areas' in driver.current_url, driver.current_url)
        driver.execute_script("document.querySelector('.facility-map-level [data-level=tract]').click()")
        check(results, 'level switches to tracts', wait_areas(driver) and area_count(driver) > 0 and 'level=tract' in driver.current_url)
        driver.execute_script("document.querySelector('.facility-map-measure [data-measure=total]').click()")
        time.sleep(0.5)
        legend = driver.execute_script("return document.querySelector('.facility-map-legend .legend-title').textContent;")
        check(results, 'measure changes the legend', 'per sq mi' not in legend, legend)
        driver.execute_script("document.querySelector('[data-view=facilities]').click()")
        check(results, 'back to facilities', feature_count(driver) > 0 and 'view=' not in driver.current_url)

        driver.get(args.base + '/tools/emissions/')
        link = driver.find_element(By.CSS_SELECTOR, '.find-area-counties a').get_attribute('href')
        driver.get(link)
        outlined = wait_loaded(driver) and driver.execute_script(
            "var m = window.EmissionsFacilityMap.instances()[0]; return !!m.outlineBounds;")
        check(results, 'county page loads, outlined', outlined, link)
        driver.execute_script("document.querySelector('[data-view=areas]').click()")
        wait_areas(driver)
        driver.find_element(By.CSS_SELECTOR, '.explorer-scope-picker[data-scope=year] .button').click()
        driver.find_element(By.CSS_SELECTOR, '.explorer-scope-picker[data-scope=year] .dropdown-item:nth-child(2)').click()
        time.sleep(1)
        kept = wait_areas(driver) and driver.execute_script(
            "var list = window.EmissionsFacilityMap.instances(); return list.length === 1 && list[0].view === 'areas';")
        check(results, 'a year change (boosted swap) keeps one map, still in Areas', kept and 'view=areas' in driver.current_url, driver.current_url)

        driver.get(args.base + '/tools/emissions/near/?lat=36.7378&lng=-119.7871&radius=3')
        near = wait_loaded(driver) and driver.execute_script(
            "var m = window.EmissionsFacilityMap.instances()[0]; return !!m.outlineBounds;")
        check(results, 'near-me page loads, with its circle', near)
```

- Update the module docstring's check list to mention the Areas view, the county page and near-me.

- [ ] **Step 9: Run the smoke script**

Rebuild assets, then hard-refresh:

```bash
docker compose -f /home/derek/dev/ccac/sjvair.com/docker-compose.yml --project-directory /home/derek/dev/ccac/sjvair.com run --rm -T -v <worktree>:/app web invoke vendor bundle styles
/home/derek/.claude/jobs/d44a9b36/tmp/venv/bin/python <worktree>/scripts/emissions_map_smoke.py --base http://localhost:8003
```

Expected: every check PASS, including `no console errors`.

Then look at it by hand at 1400 px and 390 px wide:
- Areas at each level and measure, and the popup's "Show facilities".
- A county page (washed outside, outlined) and a near-me page (circle).
- Expanded mode with the Areas controls visible.

- [ ] **Step 10: Commit**

```bash
git -C <worktree> add assets/js/emissions/facility-map.js assets/css/emissions/facility-map.css \
  camp/templates/emissions/includes/map-toolbar.html camp/apps/emissions/views.py \
  camp/apps/emissions/tests/test_views.py scripts/emissions_map_smoke.py
git -C <worktree> commit -m "feat(emissions): the map's Areas view (counties, ZIP areas, tracts), and area outlines on region and near-me pages"
```

---

### Task 9: Verify the branch

**Files:** none new.

- [ ] **Step 1: The full suite**

Run: `$TEST camp`
Expected: all PASS. Re-run once on `relation … does not exist` or connection errors (shared-DB contention).

- [ ] **Step 2: Payloads and timings on local data**

```bash
for t in county zipcode tract; do curl -s -o /dev/null -w "shapes $t: %{size_download} B %{time_total}s\n" "http://localhost:8003/api/2.0/regions/geojson/?type=$t&simplify=1&_cc=1"; done
for l in county zipcode tract; do curl -s -o /dev/null -w "values $l: %{size_download} B %{time_total}s\n" "http://localhost:8003/api/2.0/emissions/areas/?level=$l&_cc=1"; done
```

Expected: every shapes body under 900 KB, and every uncached values request under 10 s.

- [ ] **Step 3: Deploy note**

Write the deploy steps into the branch's PR-description draft at `/home/derek/.claude/jobs/d44a9b36/tmp/emissions-pr-deploy.md`:
1. `python manage.py import_population` once after deploying (and yearly, when a new ACS 5-year release lands).
2. No migrations are needed for this work.

Per the memory rule, deploy notes go in the PR description, not CLAUDE.md.

- [ ] **Step 4: Stop for Derek's review.** Report the commits (`git -C <worktree> log --oneline cea06783..`), the smoke results and the measurements.
