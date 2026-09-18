# Admin Reports Batch Two Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add four reports to the existing `camp.apps.reports` app on the same branch and PR: Coverage by Community, Data Completeness, Data Quality Problems, Pipeline Coverage.

**Architecture:** Each report is one `BaseReport` subclass in `camp/apps/reports/views.py`, one template under `camp/templates/admin/reports/`, and one test class in `camp/apps/reports/tests.py`, exactly like batch one. A small `MonitorScopeMixin` is extracted from `Coverage` so the community report shares its monitor filters instead of copying them.

**Tech Stack:** Django 5.2, PostGIS via `django.contrib.gis`, django-vanilla-views, pytest-django `TestCase`.

**Spec:** `docs/superpowers/specs/2026-09-16-admin-reports-design.md`, section "Batch two (2026-09-17)". Batch one's spec sections apply to shared conventions.

## Global Constraints

- Worktree: `/home/derek/dev/ccac/sjvair.com/.claude/worktrees/feature+admin-reports`, branch `feature/admin-reports`. Never touch the main checkout. Confirm with `git rev-parse --show-toplevel` before committing.
- Tests use `django.test.TestCase` and plain `assert`; fixtures via `fixtures = [...]`.
- Never `git add -A`; list files explicitly. Commit messages are a plain conventional subject line with NO trailers and no AI attribution of any kind.
- Timezone `America/Los_Angeles`; use `django.utils.timezone`.
- Shared report conventions: `?sjvair_only` (ED reports default off via a plain checkbox; ops reports default on with a hidden `sjvair_only=0` input before the checkbox), `?include_hidden=1`, `?county=<name>` validated against `County.names`, totals rows in `<tfoot>`, filters inside the base template's `{% block filters %}` form, `<div class="module"><table><caption>…` tables, `{% load humanize reports %}` for `intcomma` and `get_item`.
- No caching. No CSV. No JavaScript beyond `onchange="this.form.submit()"`.
- Monitor "type" means a concrete subclass; label with `type_label(cls)` (class name). ED reports use `Monitor.get_enabled_subclasses()`; ops reports use `monitor_types()` (all subclasses).
- Register new reports in this order after the existing five: `CoverageCommunity`, `DataCompleteness`, `DataQuality`, `PipelineCoverage`. Registration order is definition order in `views.py`.

## Running tests

```bash
docker compose -f /home/derek/dev/ccac/sjvair.com/docker-compose.yml \
  --project-directory /home/derek/dev/ccac/sjvair.com \
  run --rm -T -e DATABASE_URL=postgis://sjvair:changeme@db:5432/sjvair_reports \
  -v /home/derek/dev/ccac/sjvair.com/.claude/worktrees/feature+admin-reports:/app \
  test pytest camp/apps/reports/tests.py -v -p no:cacheprovider --create-db
```

`RUN_TESTS <args>` below means that command with `<args>` in place of `camp/apps/reports/tests.py -v`. The `fatal: not a git repository` line inside the container is harmless.

## Reference facts (verified)

- `camp/apps/reports/views.py` already defines: `OUTSIDE_SJV`, `DEFAULT_MAP_BOUNDS` (a `Polygon` bbox `(-122.0, 34.7, -117.5, 38.5)`), `enabled_only(queryset)`, `county_boundaries(county='')` (list of county boundary geometries), `map_bounds()`, `county_outlines()`, `monitor_types()`, `type_label(cls)`, `county_column(county)`, `per_10k(monitors, population)`, and classes `NetworkOverview`, `Coverage` (with `include_hidden`, `include_inactive`, `sjvair_only` properties, `monitors()`, `ces()`, `tracts()`, `covered()`, `county_boundaries_by_name()`), `SubscriptionCountyStats`, `FleetHealth`, `DegradedMonitors` (with `admin_url(cls, monitor)` method and `MAP_COLORS`). Imports already present: `timedelta`, `Centroid`, `Polygon`, `D`, `Count, Exists, OuterRef, Q, Sum`, `NoReverseMatch, reverse`, `timezone`, `Subscription`, `CES4, CES5`, `Monitor`, `Boundary, Region`, `BaseReport, register`, `leaflet`, `County`.
- `camp/apps/reports/tests.py` already has `StaffClientMixin` (creates a superuser and logs in), `touch(monitor, timestamp)` (creates a PM2.5 entry plus `LatestEntry`), `give_health(monitor, score, flatline_a=None, flatline_b=None)`, and imports `Point`, `timedelta`, `timezone`, `PurpleAir`, `BAM1022`, `AirGradient`, `CIMIS`, `VOZBox`, `Host`, `LatestEntry`, `HealthCheck`, `Region`, `REPORTS`, `PM25`.
- `Region.objects.counties()` returns the 8 SJV county Regions (names like `Fresno County`). `Region.Type.CITY == 'city'`, `Region.Type.CDP == 'cdp'`. `Region.boundary` is the current `Boundary` (reverse name `current_for`); `Boundary.geometry` is a `MultiPolygonField` SRID 4326; `Boundary.version` is a free string. `Region` fields: `name`, `slug`, `external_id` (unique with `type`), `type`, `boundary`.
- Fixture `regions.yaml` has the 8 county Regions with real boundaries. Fixture `calenviroscreen.yaml` has two fake Fresno tracts: 1.01 spans lon −119.8..−119.7, lat 36.7..36.8 (DAC, CES5 population 4650); 1.02 spans lon −119.7..−119.6 (not DAC, CES5 population 3350). Both are inside Fresno County.
- `MonitorSummary` (`camp/apps/summaries/models.py`): `monitor` FK, `entry_type` (string like `pm25`), `processor` (`''` for RAW), `resolution` (`BaseSummary.Resolution.DAILY == 'day'`), `timestamp` (day start, aware), `count`, `expected_count`, `sum_value`, `sum_of_squares`, `tdigest` (JSON), `minimum`, `maximum`, `mean`, `stddev`, `p25`, `p75`, `is_complete`. Unique on `(monitor, entry_type, processor, resolution, timestamp)`.
- `DefaultCalibration` (`camp/apps/calibrations/models.py`): `monitor_type` (string like `purpleair`), `entry_type` (string like `pm25`), `calibration` (string, blank means default stage). Fixture `default-calibrations.yaml` has 8 rows including `purpleair/pm25` with a non-blank calibration and `airnow/o3` with a blank one; it deliberately has no `vozbox/pm25` row.
- Entry models: `model.entry_type` (model name, e.g. `pm25`), `model.label` (class name), `model.Stage` (TextChoices: `raw`, `corrected`, `cleaned`, `calibrated`; members have `.label`). `Monitor.ENTRY_CONFIG` maps entry model → dict with optional `sensors`, `allowed_stages` (list of Stage members), `default_stage`, `processors`.
- `LatestEntry` has `monitor`, `timestamp`. `Monitor.LAST_ACTIVE_LIMIT` is 3600 seconds.
- `Host` has `name`, `email`, `phone`.

## File structure

- Modify: `camp/apps/reports/views.py` (mixin extraction + four classes)
- Modify: `camp/apps/reports/tests.py` (four test classes + one helper)
- Create: `camp/templates/admin/reports/coverage_community.html`, `data_completeness.html`, `data_quality.html`, `pipeline_coverage.html`

---

### Task 1: Coverage by Community

**Files:**
- Modify: `camp/apps/reports/views.py`
- Modify: `camp/apps/reports/tests.py`
- Create: `camp/templates/admin/reports/coverage_community.html`

**Interfaces:**
- Consumes: `Coverage.ces()`/`tracts()` logic, `enabled_only`, `per_10k`, `county_column`.
- Produces: `MonitorScopeMixin` (properties `include_hidden`, `include_inactive`, `sjvair_only`; method `monitors()`), used by `Coverage` and `CoverageCommunity`; a module-level `ces_tracts()` returning `(model, version, queryset_or_None)`; URL `reports:coverage-community`; context keys `rows`, `tiles`, `uncovered`, `sort`, plus the scope flags.

- [ ] **Step 1: Write the failing tests**

Append to `camp/apps/reports/tests.py`:

```python
from django.contrib.gis.geos import MultiPolygon, Polygon

from camp.apps.regions.models import Boundary


def make_place(name, region_type, bbox, external_id):
    """A city/CDP Region with a rectangular current boundary (lon/lat bbox)."""
    region = Region.objects.create(name=name, slug=name.lower(), type=region_type, external_id=external_id)
    boundary = Boundary.objects.create(region=region, version='latest', geometry=MultiPolygon(Polygon.from_bbox(bbox)))
    region.boundary = boundary
    region.save()
    return region


class CoverageCommunityTests(StaffClientMixin, TestCase):
    fixtures = ['regions.yaml', 'calenviroscreen.yaml']

    def setUp(self):
        super().setUp()
        # Testville covers fixture tract 1.01 (pop 4650); Emptyville covers tract 1.02 (pop 3350).
        self.testville = make_place('Testville', Region.Type.CDP, (-119.8, 36.7, -119.7, 36.8), '9001')
        self.emptyville = make_place('Emptyville', Region.Type.CITY, (-119.7, 36.7, -119.6, 36.8), '9002')
        self.monitor = PurpleAir.objects.create(name='In Testville', sensor_id=1, position=Point(-119.75, 36.75), location='outside')
        touch(self.monitor, timezone.now() - timedelta(minutes=5))

    def rows(self, **params):
        response = self.client.get(reverse('reports:coverage-community'), params)
        assert response.status_code == 200
        return response.context['rows'], response.context

    def test_rows_and_tiles(self):
        rows, context = self.rows()
        by_name = {row['name']: row for row in rows}
        assert by_name['Testville']['type'] == 'CDP'
        assert by_name['Testville']['county'] == 'Fresno'
        assert by_name['Testville']['population'] == 4650
        assert by_name['Testville']['monitors'] == 1
        assert by_name['Testville']['per_10k'] == 2.15
        assert by_name['Testville']['nearest_km'] is None
        assert by_name['Emptyville']['type'] == 'City'
        assert by_name['Emptyville']['population'] == 3350
        assert by_name['Emptyville']['monitors'] == 0
        assert by_name['Emptyville']['per_10k'] == 0.0
        assert 8.5 < by_name['Emptyville']['nearest_km'] < 9.5  # centroid (-119.65, 36.75) to the monitor
        assert context['tiles'] == {'covered': 1, 'uncovered': 1, 'uncovered_population': 3350, 'uncovered_pct': 41.9}
        # Fixture city regions (real Fresno etc.) are also listed; the two test places sort by population.
        assert rows[0]['population'] >= rows[1]['population']

    def test_uncovered_filter_and_name_sort(self):
        rows, _ = self.rows(uncovered='1')
        assert 'Testville' not in {row['name'] for row in rows}
        assert 'Emptyville' in {row['name'] for row in rows}
        rows, _ = self.rows(sort='name')
        names = [row['name'] for row in rows]
        assert names == sorted(names)

    def test_inactive_monitor_does_not_cover(self):
        Monitor.objects.filter(pk=self.monitor.pk)  # keep import used
        LatestEntry.objects.filter(monitor=self.monitor).update(timestamp=timezone.now() - timedelta(days=2))
        rows, context = self.rows()
        assert {row['name']: row for row in rows}['Testville']['monitors'] == 0
        assert context['tiles']['covered'] == 0
        rows, _ = self.rows(include_inactive='1')
        assert {row['name']: row for row in rows}['Testville']['monitors'] == 1

    def test_place_with_no_tract_centroid_uses_containing_tract(self):
        # A tiny CDP inside tract 1.01 has no tract centroid of its own.
        make_place('Tinyville', Region.Type.CDP, (-119.76, 36.74, -119.74, 36.745), '9003')
        rows, _ = self.rows()
        assert {row['name']: row for row in rows}['Tinyville']['population'] == 4650

    def test_listed_on_index(self):
        response = self.client.get(reverse('reports:index'))
        assert reverse('reports:coverage-community') in response.content.decode()
```

Also add `from camp.apps.monitors.models import Monitor` back to the imports if it is not present (batch one removed it); the test above references it.

- [ ] **Step 2: Run tests to verify they fail**

Run: `RUN_TESTS camp/apps/reports/tests.py -v -k CoverageCommunity`
Expected: FAIL with `NoReverseMatch` for `reports:coverage-community`.

- [ ] **Step 3: Extract the scope mixin and add `ces_tracts()`**

In `camp/apps/reports/views.py`, add above `class Coverage`:

```python
def ces_tracts():
    """(model, version, tract queryset) for the newest CES data present, or (None, None, None)."""
    for model in (CES5, CES4):
        version = (model._base_manager
            .order_by('-boundary__version')
            .values_list('boundary__version', flat=True)
            .first())
        if version:
            return model, version, model._base_manager.filter(boundary__version=version)
    return None, None, None


class MonitorScopeMixin:
    """Query-param toggles shared by the coverage reports."""

    @property
    def include_hidden(self):
        return self.request.GET.get('include_hidden') == '1'

    @property
    def include_inactive(self):
        return self.request.GET.get('include_inactive') == '1'

    @property
    def sjvair_only(self):
        return self.request.GET.get('sjvair_only') == '1'

    def monitors(self):
        """
        Positioned monitors of enabled types. By default only monitors that
        reported within the last hour count toward coverage; a dead monitor
        does not cover anyone.
        """
        queryset = enabled_only(Monitor.objects.filter(position__isnull=False))
        if not self.include_hidden:
            queryset = queryset.filter(is_hidden=False)
        if self.sjvair_only:
            queryset = queryset.filter(is_sjvair=True)
        if not self.include_inactive:
            cutoff = timezone.now() - timedelta(seconds=Monitor.LAST_ACTIVE_LIMIT)
            queryset = queryset.with_last_entry_timestamp().filter(last_entry_timestamp__gte=cutoff)
        return queryset

    def scope_context(self):
        return {
            'include_hidden': self.include_hidden,
            'include_inactive': self.include_inactive,
            'sjvair_only': self.sjvair_only,
        }
```

Then change `class Coverage(BaseReport)` to `class Coverage(MonitorScopeMixin, BaseReport)`, delete its own `include_hidden`, `include_inactive`, `sjvair_only` properties and its `monitors()` method, replace the body of its `ces()` with:

```python
    def ces(self):
        if not hasattr(self, '_ces'):
            model, version, _tracts = ces_tracts()
            self._ces = (model, version)
        return self._ces
```

and in its `get_context_data` replace the three scope keys with `**self.scope_context(),`. Coverage's existing tests must still pass unchanged.

- [ ] **Step 4: Add the report**

Add these imports at the top of `views.py`: `from django.contrib.gis.db.models.functions import Centroid, Distance` (replace the existing `Centroid` import line), `from django.db.models import Count, Exists, F, IntegerField, OuterRef, Q, Subquery, Sum, Value` (replace the existing line), `from django.db.models.functions import Coalesce`.

Add after `Coverage`:

```python
@register
class CoverageCommunity(MonitorScopeMixin, BaseReport):
    slug = 'coverage-community'
    title = 'Coverage by Community'
    description = 'Active monitors per city and census-designated place, with population from CalEnviroScreen tracts. Places with no monitor show the distance to the nearest one.'
    template_name = 'admin/reports/coverage_community.html'

    TYPE_LABELS = {Region.Type.CITY: 'City', Region.Type.CDP: 'CDP'}

    @property
    def uncovered(self):
        return self.request.GET.get('uncovered') == '1'

    @property
    def sort(self):
        return 'name' if self.request.GET.get('sort') == 'name' else 'population'

    def places(self):
        """City and CDP regions with a current boundary, annotated with everything the row needs."""
        _model, _version, tracts = ces_tracts()
        monitors = self.monitors()

        def count_within(queryset, geometry_ref):
            return Coalesce(Subquery(
                queryset.filter(position__within=OuterRef(geometry_ref))
                .order_by().annotate(one=Value(1)).values('one')
                .annotate(n=Count('pk')).values('n'),
                output_field=IntegerField(),
            ), 0)

        places = (Region.objects
            .filter(type__in=[Region.Type.CITY, Region.Type.CDP], boundary__isnull=False)
            .annotate(
                geometry=F('boundary__geometry'),
                centroid=Centroid('boundary__geometry'),
                monitor_count=count_within(monitors, 'geometry'),
                county_name=Subquery(
                    Region.objects.counties()
                    .filter(boundary__geometry__contains=OuterRef('centroid'))
                    .values('name')[:1]
                ),
            ))

        if tracts is not None:
            places = places.annotate(
                tract_population=Subquery(
                    tracts.annotate(tract_centroid=Centroid('boundary__geometry'))
                    .filter(tract_centroid__within=OuterRef('geometry'))
                    .order_by().annotate(one=Value(1)).values('one')
                    .annotate(p=Sum('population')).values('p'),
                    output_field=IntegerField(),
                ),
                containing_population=Subquery(
                    tracts.filter(boundary__geometry__contains=OuterRef('centroid'))
                    .values('population')[:1],
                    output_field=IntegerField(),
                ),
            )
        else:
            places = places.annotate(
                tract_population=Value(None, output_field=IntegerField()),
                containing_population=Value(None, output_field=IntegerField()),
            )

        return places.values('sqid', 'name', 'type', 'centroid', 'monitor_count', 'county_name',
                             'tract_population', 'containing_population')

    def nearest_km(self, centroid):
        distance = (self.monitors()
            .annotate(distance=Distance('position', centroid))
            .order_by('distance')
            .values_list('distance', flat=True)
            .first())
        return round(distance.km, 1) if distance is not None else None

    def get_rows(self):
        rows = []
        for place in self.places():
            population = place['tract_population']
            if population is None:
                population = place['containing_population'] or 0
            county_name = place['county_name'] or ''
            row = {
                'name': place['name'],
                'type': self.TYPE_LABELS.get(place['type'], place['type']),
                'county': county_column(county_name.removesuffix(' County')),
                'population': population,
                'monitors': place['monitor_count'],
                'per_10k': per_10k(place['monitor_count'], population),
                'nearest_km': None if place['monitor_count'] else self.nearest_km(place['centroid']),
                'sqid': place['sqid'],
            }
            if self.uncovered and row['monitors']:
                continue
            rows.append(row)

        if self.sort == 'name':
            rows.sort(key=lambda row: row['name'])
        else:
            rows.sort(key=lambda row: (-row['population'], row['name']))
        return rows

    def get_tiles(self, rows):
        # Tiles describe every place, even when ?uncovered=1 narrows the table.
        all_rows = rows if not self.uncovered else self.all_rows
        covered = sum(1 for row in all_rows if row['monitors'])
        uncovered_population = sum(row['population'] for row in all_rows if not row['monitors'])
        total_population = sum(row['population'] for row in all_rows)
        return {
            'covered': covered,
            'uncovered': len(all_rows) - covered,
            'uncovered_population': uncovered_population,
            'uncovered_pct': round(uncovered_population / total_population * 100, 1) if total_population else None,
        }

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        return {
            **context,
            **self.scope_context(),
            'uncovered': self.uncovered,
            'sort': self.sort,
            'tiles': self.get_tiles(context['rows']),
        }
```

`get_tiles` references `self.all_rows` for the uncovered case; make `get_rows()` set `self.all_rows` to the full (unfiltered) row list before applying the `uncovered` filter. Concretely: build every row into `all_rows`, set `self.all_rows = all_rows`, then `rows = [r for r in all_rows if not (self.uncovered and r['monitors'])]`, then sort `rows`.

`Distance('position', centroid)` on a geodetic point field yields meters via `ST_DistanceSphere`; `.km` converts. The `centroid` value from `.values()` is a `Point`.

Notes for the implementer on the two risks: (1) `OuterRef('geometry')` / `OuterRef('centroid')` reference annotations on the outer queryset; Django supports this. (2) If `Centroid` inside the tract subquery combined with `__within=OuterRef(...)` errors, fall back to `Subquery(tracts.filter(boundary__geometry__intersects=OuterRef('geometry'))...)` is NOT acceptable (it double counts border tracts); instead compute `tract_population` in Python per place using `Centroid` on the outer query only: for each place, `tracts.annotate(c=Centroid('boundary__geometry')).filter(c__within=place_geometry).aggregate(Sum('population'))`. Report which path you used.

- [ ] **Step 5: Template**

`camp/templates/admin/reports/coverage_community.html`:

```django
{% extends 'admin/reports/base.html' %}
{% load humanize %}

{% block filters %}
<label><input type="checkbox" name="uncovered" value="1" {% if uncovered %}checked{% endif %} onchange="this.form.submit()"> Only places with no monitor</label>
<label>Sort
    <select name="sort" onchange="this.form.submit()">
        <option value="population" {% if sort == 'population' %}selected{% endif %}>Population</option>
        <option value="name" {% if sort == 'name' %}selected{% endif %}>Name</option>
    </select>
</label>
<label><input type="checkbox" name="sjvair_only" value="1" {% if sjvair_only %}checked{% endif %} onchange="this.form.submit()"> SJVAir monitors only</label>
<label><input type="checkbox" name="include_hidden" value="1" {% if include_hidden %}checked{% endif %} onchange="this.form.submit()"> Include hidden monitors</label>
<label><input type="checkbox" name="include_inactive" value="1" {% if include_inactive %}checked{% endif %} onchange="this.form.submit()"> Include inactive monitors</label>
{% endblock %}

{% block report %}
<div class="module">
    <table>
        <caption>Communities</caption>
        <tr><th>With a monitor</th><td>{{ tiles.covered|intcomma }}</td></tr>
        <tr><th>Without a monitor</th><td>{{ tiles.uncovered|intcomma }}</td></tr>
        <tr><th>Population without a monitor</th><td>{{ tiles.uncovered_population|intcomma }}{% if tiles.uncovered_pct is not None %} ({{ tiles.uncovered_pct }}%){% endif %}</td></tr>
    </table>
</div>

<div class="module">
    <table>
        <caption>{{ rows|length }} cities and census-designated places</caption>
        <thead>
            <tr><th>Place</th><th>Type</th><th>County</th><th>Population</th><th>Monitors</th><th>Per 10k</th><th>Nearest monitor</th></tr>
        </thead>
        <tbody>
            {% for row in rows %}
            <tr>
                <th>{{ row.name }}</th>
                <td>{{ row.type }}</td>
                <td>{{ row.county }}</td>
                <td>{{ row.population|intcomma }}</td>
                <td>{{ row.monitors|intcomma }}</td>
                <td>{{ row.per_10k|default_if_none:"—" }}</td>
                <td>{% if row.nearest_km is not None %}{{ row.nearest_km }} km{% else %}—{% endif %}</td>
            </tr>
            {% empty %}
            <tr><td colspan="7">No city or CDP regions loaded. Run the regions imports first.</td></tr>
            {% endfor %}
        </tbody>
    </table>
</div>
{% endblock %}
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `RUN_TESTS camp/apps/reports/tests.py -v`
Expected: all PASS, including the untouched `CoverageTests`. The `tiles['uncovered_pct']` expected value is 3350 / 8000 = 41.875 → `41.9`; if the fixture's real city regions (e.g. Fresno) pick up population from the fake tracts and change the totals, adjust the test to compute the expected percentage from the rows it reads rather than hardcoding it, and say so in the report.

- [ ] **Step 7: Commit**

```bash
git add camp/apps/reports/views.py camp/apps/reports/tests.py camp/templates/admin/reports/coverage_community.html
git commit -m "feat(reports): add coverage by community report"
```

---

### Task 2: Data Completeness

**Files:**
- Modify: `camp/apps/reports/views.py`
- Modify: `camp/apps/reports/tests.py`
- Create: `camp/templates/admin/reports/data_completeness.html`

**Interfaces:**
- Consumes: `monitor_types()`, `type_label()`, `County.names`, `DegradedMonitors.admin_url` pattern.
- Produces: URL `reports:data-completeness`; context `rows` (per type), `low` (per monitor), `entry_type`, `entry_types`, `threshold`, `county`, `sjvair_only`, `include_hidden`, `windows`. Test helper `daily_summary(monitor, day, count, expected, entry_type='pm25')`.

- [ ] **Step 1: Write the failing tests**

Append to `camp/apps/reports/tests.py`:

```python
from datetime import datetime

from camp.apps.summaries.models import MonitorSummary


def daily_summary(monitor, day, count, expected, entry_type='pm25'):
    """A RAW daily MonitorSummary for `day` (a date) with the given count/expected."""
    timestamp = timezone.make_aware(datetime.combine(day, datetime.min.time()))
    return MonitorSummary.objects.create(
        monitor=monitor, entry_type=entry_type, processor='',
        resolution=MonitorSummary.Resolution.DAILY, timestamp=timestamp,
        count=count, expected_count=expected, sum_value=float(count), sum_of_squares=float(count),
        tdigest={}, minimum=1.0, maximum=1.0, mean=1.0, stddev=0.0, p25=1.0, p75=1.0,
        is_complete=count >= expected,
    )


class DataCompletenessTests(StaffClientMixin, TestCase):
    def setUp(self):
        super().setUp()
        self.good = PurpleAir.objects.create(name='Good', sensor_id=1, position=Point(-119.75, 36.75), location='outside', is_sjvair=True)
        self.bad = PurpleAir.objects.create(name='Bad', sensor_id=2, position=Point(-119.0, 35.4), location='outside', is_sjvair=True)
        self.partner = PurpleAir.objects.create(name='Partner', sensor_id=3, position=Point(-119.75, 36.75), location='outside')
        self.silent = PurpleAir.objects.create(name='Silent', sensor_id=4, position=Point(-119.75, 36.75), location='outside', is_sjvair=True)
        self.bam = BAM1022.objects.create(name='BAM', position=Point(-119.75, 36.75), location='outside', is_sjvair=True)
        yesterday = timezone.localdate() - timedelta(days=1)
        for offset in range(7):
            day = yesterday - timedelta(days=offset)
            daily_summary(self.good, day, 720, 720)
            daily_summary(self.bad, day, 360, 720)
            daily_summary(self.partner, day, 720, 720)
            daily_summary(self.bam, day, 24, 24)
        for offset in range(7, 30):
            daily_summary(self.good, yesterday - timedelta(days=offset), 720, 720)
        # Today's partial day must not count.
        daily_summary(self.good, timezone.localdate(), 10, 720)

    def rows(self, **params):
        response = self.client.get(reverse('reports:data-completeness'), params)
        assert response.status_code == 200
        return response.context

    def test_per_type_windows(self):
        context = self.rows()
        purpleair = {r['type']: r for r in context['rows']}['PurpleAir']
        # SJVAir only by default: Good, Bad, Silent (no rows) -> 7d: (720+360)*7 / 720*14 ... Silent has no expected rows.
        assert purpleair['monitors'] == 3
        assert purpleair['received_7'] == (720 + 360) * 7
        assert purpleair['expected_7'] == 720 * 14
        assert purpleair['pct_7'] == 75.0
        assert purpleair['received_30'] == 720 * 30 + 360 * 7
        assert purpleair['expected_30'] == 720 * 30 + 720 * 7
        bam = {r['type']: r for r in context['rows']}['BAM1022']
        assert bam['pct_7'] == 100.0
        assert context['entry_type'] == 'pm25'

    def test_low_table_worst_first_with_silent_monitors_on_top(self):
        context = self.rows()
        low = [(r['name'], r['pct_7']) for r in context['low']]
        assert low == [('Silent', 0.0), ('Bad', 50.0)]
        assert context['low'][1]['admin_url'] == reverse('admin:purpleair_purpleair_change', args=[self.bad.pk])

    def test_threshold_and_scope_filters(self):
        assert [r['name'] for r in self.rows(threshold='40')['low']] == ['Silent']
        assert 'Partner' in [r['name'] for r in self.rows(sjvair_only='0')['low']] or True  # Partner is at 100%, never low
        purpleair = {r['type']: r for r in self.rows(sjvair_only='0')['rows']}['PurpleAir']
        assert purpleair['monitors'] == 4
        purpleair = {r['type']: r for r in self.rows(county='Kern')['rows']}['PurpleAir']
        assert purpleair['monitors'] == 1
        assert purpleair['pct_7'] == 50.0

    def test_entry_type_selector(self):
        daily_summary(self.good, timezone.localdate() - timedelta(days=1), 100, 200, entry_type='humidity')
        context = self.rows(entry_type='humidity')
        purpleair = {r['type']: r for r in context['rows']}['PurpleAir']
        assert purpleair['pct_7'] == 50.0
        assert ('humidity', 'Humidity') in context['entry_types']
        assert self.rows(entry_type='nope')['entry_type'] == 'pm25'
```

Remove the throwaway `or True` line in `test_threshold_and_scope_filters` (it is there only to illustrate; write the assertion as `assert 'Partner' not in [...]` since Partner is at 100% and never low).

- [ ] **Step 2: Run tests to verify they fail**

Run: `RUN_TESTS camp/apps/reports/tests.py -v -k DataCompleteness`
Expected: FAIL with `NoReverseMatch`.

- [ ] **Step 3: Implement**

Add `from camp.apps.summaries.models import MonitorSummary` to the imports in `views.py`. Add a module-level helper (near `type_label`):

```python
def admin_change_url(cls, monitor):
    """Change-page URL, or '' when the subclass isn't registered in the admin."""
    try:
        return reverse(f'admin:{cls._meta.app_label}_{cls._meta.model_name}_change', args=[monitor.pk])
    except NoReverseMatch:
        return ''
```

and make `DegradedMonitors.admin_url` call it (`return admin_change_url(cls, monitor)`), keeping the method so nothing else changes.

Add after `FleetHealth`:

```python
@register
class DataCompleteness(BaseReport):
    slug = 'data-completeness'
    title = 'Data Completeness'
    description = 'Share of expected readings actually received, from the daily summaries. Calendar days ending yesterday. SJVAir monitors only unless toggled.'
    template_name = 'admin/reports/data_completeness.html'

    DEFAULT_ENTRY_TYPE = 'pm25'
    DEFAULT_THRESHOLD = 80
    WINDOWS = (7, 30)

    @property
    def county(self):
        county = self.request.GET.get('county', '')
        return county if county in County.names else ''

    @property
    def sjvair_only(self):
        return self.request.GET.get('sjvair_only', '1') == '1'

    @property
    def include_hidden(self):
        return self.request.GET.get('include_hidden') == '1'

    @property
    def threshold(self):
        try:
            return min(100, max(0, int(self.request.GET.get('threshold', self.DEFAULT_THRESHOLD))))
        except (TypeError, ValueError):
            return self.DEFAULT_THRESHOLD

    def entry_types(self):
        """(entry_type, label) for every entry type any monitor type produces."""
        models = {model for cls in monitor_types() for model in cls.ENTRY_CONFIG}
        return sorted(((model.entry_type, model.label) for model in models), key=lambda item: item[1])

    @property
    def entry_type(self):
        wanted = self.request.GET.get('entry_type', self.DEFAULT_ENTRY_TYPE)
        return wanted if wanted in {key for key, _label in self.entry_types()} else self.DEFAULT_ENTRY_TYPE

    def window(self, days):
        """(start, end) aware datetimes covering the `days` calendar days ending yesterday."""
        end_date = timezone.localdate()
        end = timezone.make_aware(datetime.combine(end_date, datetime.min.time()))
        return end - timedelta(days=days), end

    def scoped(self, queryset):
        if not self.include_hidden:
            queryset = queryset.filter(is_hidden=False)
        if self.sjvair_only:
            queryset = queryset.filter(is_sjvair=True)
        if self.county:
            queryset = queryset.filter(county=self.county)
        return queryset

    def producing_types(self):
        """Monitor types whose config produces the selected entry type."""
        return [cls for cls in monitor_types() if any(m.entry_type == self.entry_type for m in cls.ENTRY_CONFIG)]

    def summaries(self, days):
        start, end = self.window(days)
        return MonitorSummary.objects.filter(
            resolution=MonitorSummary.Resolution.DAILY,
            processor='',
            entry_type=self.entry_type,
            timestamp__gte=start,
            timestamp__lt=end,
        )

    @staticmethod
    def pct(received, expected):
        return round(received / expected * 100, 1) if expected else 0.0

    def get_rows(self):
        rows = []
        for cls in self.producing_types():
            monitors = self.scoped(cls.objects.all())
            row = {'type': type_label(cls), 'monitors': monitors.count()}
            for days in self.WINDOWS:
                stats = self.summaries(days).filter(monitor__in=monitors.values('pk')).aggregate(
                    received=Coalesce(Sum('count'), 0), expected=Coalesce(Sum('expected_count'), 0),
                )
                row[f'received_{days}'] = stats['received']
                row[f'expected_{days}'] = stats['expected']
                row[f'pct_{days}'] = self.pct(stats['received'], stats['expected'])
            rows.append(row)
        return rows

    def get_low(self):
        days = self.WINDOWS[0]
        totals = {
            item['monitor']: item
            for item in (self.summaries(days)
                .values('monitor')
                .annotate(received=Sum('count'), expected=Sum('expected_count')))
        }
        low = []
        for cls in self.producing_types():
            for monitor in self.scoped(cls.objects.all()).select_related('host'):
                stats = totals.get(monitor.pk, {'received': 0, 'expected': 0})
                pct = self.pct(stats['received'], stats['expected'])
                if pct >= self.threshold:
                    continue
                low.append({
                    'name': monitor.name,
                    'type': type_label(cls),
                    'county': monitor.county,
                    'host': monitor.host.name if monitor.host_id else '',
                    'received': stats['received'],
                    'expected': stats['expected'],
                    'pct_7': pct,
                    'admin_url': admin_change_url(cls, monitor),
                })
        low.sort(key=lambda row: (row['pct_7'], row['name']))
        return low

    def get_context_data(self, **kwargs):
        return {
            **super().get_context_data(**kwargs),
            'counties': County.names,
            'county': self.county,
            'sjvair_only': self.sjvair_only,
            'include_hidden': self.include_hidden,
            'entry_type': self.entry_type,
            'entry_types': self.entry_types(),
            'threshold': self.threshold,
            'windows': self.WINDOWS,
            'low': self.get_low(),
        }
```

Add `from datetime import datetime, timedelta` (replace the existing `timedelta` import). Note `monitor__in=monitors.values('pk')` keeps the type restriction inside one query per window.

- [ ] **Step 4: Template**

`camp/templates/admin/reports/data_completeness.html`:

```django
{% extends 'admin/reports/base.html' %}
{% load humanize %}

{% block filters %}
<label>Entry type
    <select name="entry_type" onchange="this.form.submit()">
        {% for value, label in entry_types %}<option value="{{ value }}" {% if value == entry_type %}selected{% endif %}>{{ label }}</option>{% endfor %}
    </select>
</label>
<label>County
    <select name="county" onchange="this.form.submit()">
        <option value="">All counties</option>
        {% for name in counties %}<option value="{{ name }}" {% if name == county %}selected{% endif %}>{{ name }}</option>{% endfor %}
    </select>
</label>
<label>Low threshold % <input type="number" name="threshold" value="{{ threshold }}" min="0" max="100" step="5"></label>
<input type="hidden" name="sjvair_only" value="0">
<label><input type="checkbox" name="sjvair_only" value="1" {% if sjvair_only %}checked{% endif %} onchange="this.form.submit()"> SJVAir monitors only</label>
<label><input type="checkbox" name="include_hidden" value="1" {% if include_hidden %}checked{% endif %} onchange="this.form.submit()"> Include hidden</label>
<button type="submit">Apply</button>
{% endblock %}

{% block report %}
<div class="module">
    <table>
        <caption>Readings received vs expected, by type</caption>
        <thead>
            <tr><th>Type</th><th>Monitors</th><th>7d received</th><th>7d expected</th><th>7d %</th><th>30d received</th><th>30d expected</th><th>30d %</th></tr>
        </thead>
        <tbody>
            {% for row in rows %}
            <tr>
                <th>{{ row.type }}</th>
                <td>{{ row.monitors|intcomma }}</td>
                <td>{{ row.received_7|intcomma }}</td><td>{{ row.expected_7|intcomma }}</td><td>{{ row.pct_7 }}%</td>
                <td>{{ row.received_30|intcomma }}</td><td>{{ row.expected_30|intcomma }}</td><td>{{ row.pct_30 }}%</td>
            </tr>
            {% empty %}
            <tr><td colspan="8">No monitor type produces this entry type.</td></tr>
            {% endfor %}
        </tbody>
    </table>
</div>

<div class="module">
    <table>
        <caption>{{ low|length }} monitor{{ low|length|pluralize }} below {{ threshold }}% over 7 days</caption>
        <thead>
            <tr><th>Monitor</th><th>Type</th><th>County</th><th>Host</th><th>Received</th><th>Expected</th><th>7d %</th></tr>
        </thead>
        <tbody>
            {% for row in low %}
            <tr>
                <th>{% if row.admin_url %}<a href="{{ row.admin_url }}">{{ row.name }}</a>{% else %}{{ row.name }}{% endif %}</th>
                <td>{{ row.type }}</td>
                <td>{{ row.county }}</td>
                <td>{{ row.host }}</td>
                <td>{{ row.received|intcomma }}</td>
                <td>{{ row.expected|intcomma }}</td>
                <td>{{ row.pct_7 }}%</td>
            </tr>
            {% empty %}
            <tr><td colspan="7">Everything is above the threshold.</td></tr>
            {% endfor %}
        </tbody>
    </table>
</div>
{% endblock %}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `RUN_TESTS camp/apps/reports/tests.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add camp/apps/reports/views.py camp/apps/reports/tests.py camp/templates/admin/reports/data_completeness.html
git commit -m "feat(reports): add data completeness report"
```

---

### Task 3: Data Quality Problems

**Files:**
- Modify: `camp/apps/reports/views.py`
- Modify: `camp/apps/reports/tests.py`
- Create: `camp/templates/admin/reports/data_quality.html`

**Interfaces:**
- Consumes: `monitor_types()`, `type_label()`, `admin_change_url()`, `DEFAULT_MAP_BOUNDS`, `Region.objects.counties()`, `LatestEntry`.
- Produces: URL `reports:data-quality`; context `rows`, `tiles` (dict: `total` plus one key per condition label), `types`, `monitor_type`, `counties`, `county`.

- [ ] **Step 1: Write the failing tests**

Append to `camp/apps/reports/tests.py`:

```python
class DataQualityTests(StaffClientMixin, TestCase):
    fixtures = ['regions.yaml']

    def setUp(self):
        super().setUp()
        host = Host.objects.create(name='Library')
        fresno = Point(-119.75, 36.75)
        self.fine = PurpleAir.objects.create(name='Fine', sensor_id=1, position=fresno, location='outside', is_sjvair=True, host=host)
        self.outsider = PurpleAir.objects.create(name='Paso Robles', sensor_id=2, position=Point(-120.69, 35.63), location='outside')
        self.no_position = PurpleAir.objects.create(name='No position', sensor_id=3, location='outside')
        self.bogus = PurpleAir.objects.create(name='Bogus', sensor_id=4, position=Point(0, 0), location='outside')
        self.no_name = PurpleAir.objects.create(name='', sensor_id=5, position=fresno, location='outside')
        self.no_county = PurpleAir.objects.create(name='No county', sensor_id=6, position=fresno, location='outside')
        Monitor.objects.filter(pk=self.no_county.pk).update(county='')
        self.wrong_county = PurpleAir.objects.create(name='Wrong county', sensor_id=7, position=fresno, location='outside')
        Monitor.objects.filter(pk=self.wrong_county.pk).update(county='Kern')
        self.hidden = PurpleAir.objects.create(name='Hidden reporting', sensor_id=8, position=fresno, location='outside', is_hidden=True)
        touch(self.hidden, timezone.now() - timedelta(minutes=5))
        self.no_host = BAM1022.objects.create(name='No host', position=fresno, location='outside', is_sjvair=True)

    def rows(self, **params):
        response = self.client.get(reverse('reports:data-quality'), params)
        assert response.status_code == 200
        return response.context

    def test_each_check_fires_once_and_clean_monitors_are_absent(self):
        context = self.rows()
        by_name = {row['name']: row['condition'] for row in context['rows']}
        assert by_name == {
            'No position': 'No position',
            'Bogus': 'Bogus position',
            self.no_name.pk: 'No name',
            'No county': 'No county',
            'Wrong county': 'Wrong county',
            'Hidden reporting': 'Hidden but reporting',
            'No host': 'No host',
        }
        assert context['tiles']['total'] == 7
        assert context['tiles']['No county'] == 1

    def test_sorted_by_check_order_then_name(self):
        names = [row['name'] for row in self.rows()['rows']]
        assert names == ['No position', 'Bogus', self.no_name.pk, 'No county', 'Wrong county', 'Hidden reporting', 'No host']

    def test_columns_and_filters(self):
        context = self.rows()
        row = {r['name']: r for r in context['rows']}['Wrong county']
        assert row['type'] == 'PurpleAir'
        assert row['county'] == 'Kern'
        assert row['position'] == '36.7500, -119.7500'
        assert row['admin_url'] == reverse('admin:purpleair_purpleair_change', args=[self.wrong_county.pk])
        assert [r['name'] for r in self.rows(type='bam1022')['rows']] == ['No host']
        assert [r['name'] for r in self.rows(county='Kern')['rows']] == ['Wrong county']
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `RUN_TESTS camp/apps/reports/tests.py -v -k DataQuality`
Expected: FAIL with `NoReverseMatch`.

- [ ] **Step 3: Implement**

Add `from django.db.models.functions import Coalesce, Concat` (extend the existing import) and `from camp.apps.monitors.models import LatestEntry, Monitor` (extend). Add after `DegradedMonitors`:

```python
@register
class DataQuality(BaseReport):
    slug = 'data-quality'
    title = 'Data Quality Problems'
    description = 'Monitors with broken metadata: missing or bogus positions, blank names, county mismatches, hidden monitors still reporting, SJVAir monitors with no host. Every type, hidden included.'
    template_name = 'admin/reports/data_quality.html'

    # (annotation/lookup name, label) in severity order. Each maps to a boolean annotation.
    CHECKS = [
        ('no_position', 'No position'),
        ('bogus_position', 'Bogus position'),
        ('no_name', 'No name'),
        ('no_county', 'No county'),
        ('wrong_county', 'Wrong county'),
        ('hidden_reporting', 'Hidden but reporting'),
        ('no_host', 'No host'),
    ]

    @property
    def county(self):
        county = self.request.GET.get('county', '')
        return county if county in County.names else ''

    @property
    def monitor_type(self):
        wanted = self.request.GET.get('type', '')
        return wanted if wanted in {cls.monitor_type for cls in monitor_types()} else ''

    def annotated(self, queryset):
        cutoff = timezone.now() - timedelta(seconds=Monitor.LAST_ACTIVE_LIMIT)
        county_boundaries = Boundary.objects.filter(current_for__in=Region.objects.counties())
        return queryset.annotate(
            county_region_name=Concat('county', Value(' County')),
            in_sjv=Exists(county_boundaries.filter(geometry__contains=OuterRef('position'))),
            in_own_county=Exists(county_boundaries.filter(
                current_for__name=OuterRef('county_region_name'),
                geometry__contains=OuterRef('position'),
            )),
            reporting=Exists(LatestEntry.objects.filter(monitor=OuterRef('pk'), timestamp__gte=cutoff)),
        ).annotate(
            no_position=Q(position__isnull=True),
            bogus_position=Q(position__isnull=False) & ~Q(position__within=DEFAULT_MAP_BOUNDS),
            no_name=Q(name=''),
            no_county=Q(county='') & Q(in_sjv=True),
            wrong_county=~Q(county='') & Q(position__isnull=False) & Q(in_own_county=False),
            hidden_reporting=Q(is_hidden=True) & Q(reporting=True),
            no_host=Q(is_sjvair=True) & Q(host__isnull=True),
        )

    def get_rows(self):
        flagged = Q()
        for key, _label in self.CHECKS:
            flagged |= Q(**{key: True})

        rows = []
        for cls in monitor_types():
            if self.monitor_type and cls.monitor_type != self.monitor_type:
                continue
            queryset = self.annotated(cls.objects.all()).filter(flagged)
            if self.county:
                queryset = queryset.filter(county=self.county)
            for monitor in queryset:
                conditions = [label for key, label in self.CHECKS if getattr(monitor, key)]
                first = next(i for i, (key, _l) in enumerate(self.CHECKS) if getattr(monitor, key))
                rows.append({
                    'name': monitor.name or monitor.pk,
                    'type': type_label(cls),
                    'county': monitor.county,
                    'position': f'{monitor.position.y:.4f}, {monitor.position.x:.4f}' if monitor.position else '',
                    'condition': ', '.join(conditions),
                    'conditions': conditions,
                    'admin_url': admin_change_url(cls, monitor),
                    'sort_key': (first, str(monitor.name or monitor.pk)),
                })
        rows.sort(key=lambda row: row['sort_key'])
        return rows

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        tiles = {'total': len(context['rows'])}
        for _key, label in self.CHECKS:
            tiles[label] = sum(1 for row in context['rows'] if label in row['conditions'])
        return {
            **context,
            'tiles': tiles,
            'checks': [label for _key, label in self.CHECKS],
            'counties': County.names,
            'county': self.county,
            'monitor_type': self.monitor_type,
            'types': [(cls.monitor_type, type_label(cls)) for cls in monitor_types()],
        }
```

Notes: boolean annotations via `annotate(name=Q(...))` are supported on Django 5.2 (a `Q` annotates as a boolean expression). If the ORM rejects `~Q(position__within=...)` on a null position, the `Q(position__isnull=False) &` guard already precedes it. `OuterRef('county_region_name')` references the outer annotation; Django resolves it. The `no_name` row's name is the pk, and `sort_key` stringifies it so it sorts with the other names.

- [ ] **Step 4: Template**

`camp/templates/admin/reports/data_quality.html`:

```django
{% extends 'admin/reports/base.html' %}
{% load humanize reports %}

{% block filters %}
<label>Type
    <select name="type" onchange="this.form.submit()">
        <option value="">All types</option>
        {% for value, label in types %}<option value="{{ value }}" {% if value == monitor_type %}selected{% endif %}>{{ label }}</option>{% endfor %}
    </select>
</label>
<label>County
    <select name="county" onchange="this.form.submit()">
        <option value="">All counties</option>
        {% for name in counties %}<option value="{{ name }}" {% if name == county %}selected{% endif %}>{{ name }}</option>{% endfor %}
    </select>
</label>
{% endblock %}

{% block report %}
<div class="module">
    <table>
        <caption>Problems found</caption>
        <tr><th>Monitors flagged</th><td>{{ tiles.total|intcomma }}</td></tr>
        {% for label in checks %}
        <tr><th>{{ label }}</th><td>{{ tiles|get_item:label|intcomma }}</td></tr>
        {% endfor %}
    </table>
</div>

<div class="module">
    <table>
        <caption>{{ rows|length }} monitor{{ rows|length|pluralize }} with problems</caption>
        <thead><tr><th>Monitor</th><th>Type</th><th>County</th><th>Position</th><th>Problem</th></tr></thead>
        <tbody>
            {% for row in rows %}
            <tr>
                <th>{% if row.admin_url %}<a href="{{ row.admin_url }}">{{ row.name }}</a>{% else %}{{ row.name }}{% endif %}</th>
                <td>{{ row.type }}</td>
                <td>{{ row.county }}</td>
                <td>{{ row.position }}</td>
                <td>{{ row.condition }}</td>
            </tr>
            {% empty %}
            <tr><td colspan="5">No problems found.</td></tr>
            {% endfor %}
        </tbody>
    </table>
</div>
{% endblock %}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `RUN_TESTS camp/apps/reports/tests.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add camp/apps/reports/views.py camp/apps/reports/tests.py camp/templates/admin/reports/data_quality.html
git commit -m "feat(reports): add data quality problems report"
```

---

### Task 4: Pipeline Coverage

**Files:**
- Modify: `camp/apps/reports/views.py`
- Modify: `camp/apps/reports/tests.py`
- Create: `camp/templates/admin/reports/pipeline_coverage.html`

**Interfaces:**
- Consumes: `Monitor.get_enabled_subclasses()`, `type_label()`, `DefaultCalibration`.
- Produces: URL `reports:pipeline-coverage`; context `rows` (one dict per type; key `type` plus one key per entry type holding a cell dict or `None`), `entry_types` (list of `(entry_type, label)`), `orphans`, `unpublished_count`.

- [ ] **Step 1: Write the failing tests**

Append to `camp/apps/reports/tests.py`:

```python
from camp.apps.calibrations.models import DefaultCalibration


class PipelineCoverageTests(StaffClientMixin, TestCase):
    fixtures = ['default-calibrations.yaml']

    def test_matrix_cells(self):
        response = self.client.get(reverse('reports:pipeline-coverage'))
        assert response.status_code == 200
        rows = {row['type']: row for row in response.context['rows']}
        pm25 = rows['PurpleAir']['pm25']
        assert pm25['published'] is True
        assert pm25['calibration'] == DefaultCalibration.objects.get(monitor_type='purpleair', entry_type='pm25').calibration
        assert 'Raw' in pm25['stages']
        assert rows['PurpleAir']['humidity']['published'] is False
        assert rows['VOZBox']['pm25']['published'] is False
        assert rows['BAM1022']['humidity'] is None or rows['BAM1022']['humidity']['published'] is False
        assert ('pm25', 'PM25') in response.context['entry_types']
        assert response.context['unpublished_count'] > 0

    def test_orphaned_publish_rows(self):
        DefaultCalibration.objects.create(monitor_type='purpleair', entry_type='co2', calibration='')
        response = self.client.get(reverse('reports:pipeline-coverage'))
        orphans = [(o['monitor_type'], o['entry_type']) for o in response.context['orphans']]
        assert ('purpleair', 'co2') in orphans
        assert ('purpleair', 'pm25') not in orphans
```

If `BAM1022` produces humidity in its config, the `is None or ...` assertion still holds; keep it as written.

- [ ] **Step 2: Run tests to verify they fail**

Run: `RUN_TESTS camp/apps/reports/tests.py -v -k PipelineCoverage`
Expected: FAIL with `NoReverseMatch`.

- [ ] **Step 3: Implement**

Add `from camp.apps.calibrations.models import DefaultCalibration` to the imports. Add at the end of `views.py`:

```python
@register
class PipelineCoverage(BaseReport):
    slug = 'pipeline-coverage'
    title = 'Pipeline Coverage'
    description = 'Which entry types each enabled monitor type produces, the stages its config allows, and whether the pair is published on the map (a DefaultCalibration row).'
    template_name = 'admin/reports/pipeline_coverage.html'

    def entry_models(self, types):
        models = {model for cls in types for model in cls.ENTRY_CONFIG}
        return sorted(models, key=lambda model: model.entry_type)

    def get_rows(self):
        types = Monitor.get_enabled_subclasses()
        published = {(d.monitor_type, d.entry_type): d.calibration for d in DefaultCalibration.objects.all()}
        self.produced = set()
        self.unpublished_count = 0

        rows = []
        for cls in types:
            row = {'type': type_label(cls)}
            for model in self.entry_models(types):
                config = cls.ENTRY_CONFIG.get(model)
                if not config:
                    row[model.entry_type] = None
                    continue
                key = (cls.monitor_type, model.entry_type)
                self.produced.add(key)
                stages = config.get('allowed_stages') or [model.Stage.RAW]
                is_published = key in published
                if not is_published:
                    self.unpublished_count += 1
                row[model.entry_type] = {
                    'stages': ' → '.join(stage.label for stage in stages),
                    'default': config.get('default_stage', model.Stage.RAW).label,
                    'published': is_published,
                    'calibration': published.get(key) or '',
                }
            rows.append(row)
        return rows

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        types = Monitor.get_enabled_subclasses()
        orphans = [
            {'monitor_type': d.monitor_type, 'entry_type': d.entry_type, 'calibration': d.calibration}
            for d in DefaultCalibration.objects.order_by('monitor_type', 'entry_type')
            if (d.monitor_type, d.entry_type) not in self.produced
        ]
        return {
            **context,
            'entry_types': [(model.entry_type, model.label) for model in self.entry_models(types)],
            'orphans': orphans,
            'unpublished_count': self.unpublished_count,
        }
```

`stage.label` works because `allowed_stages` holds `Stage` enum members; if a config stores plain strings, wrap with `model.Stage(stage).label`.

- [ ] **Step 4: Template**

`camp/templates/admin/reports/pipeline_coverage.html`:

```django
{% extends 'admin/reports/base.html' %}
{% load humanize reports %}

{% block extrastyle %}
    {{ block.super }}
    <style>
        .pipeline-cell { font-size: 0.75rem; line-height: 1.3; }
        .pipeline-cell.is-unpublished { color: var(--error-fg); }
        .pipeline-cell .pipeline-published { font-weight: bold; }
    </style>
{% endblock %}

{% block report %}
<p>{{ unpublished_count }} produced (type, entry type) pair{{ unpublished_count|pluralize }} {{ unpublished_count|pluralize:"is,are" }} not published on the map. Publishing is a row in <code>fixtures/default-calibrations.yaml</code>.</p>

<div class="module">
    <table>
        <caption>Entry types by monitor type</caption>
        <thead>
            <tr><th>Type</th>{% for value, label in entry_types %}<th>{{ label }}</th>{% endfor %}</tr>
        </thead>
        <tbody>
            {% for row in rows %}
            <tr>
                <th>{{ row.type }}</th>
                {% for value, label in entry_types %}
                {% with cell=row|get_item:value %}
                <td>
                    {% if cell %}
                    <div class="pipeline-cell {% if not cell.published %}is-unpublished{% endif %}">
                        <div>{{ cell.stages }}</div>
                        <div>default: {{ cell.default }}</div>
                        {% if cell.published %}
                        <div class="pipeline-published">published{% if cell.calibration %}: {{ cell.calibration }}{% endif %}</div>
                        {% else %}
                        <div>not published</div>
                        {% endif %}
                    </div>
                    {% endif %}
                </td>
                {% endwith %}
                {% endfor %}
            </tr>
            {% endfor %}
        </tbody>
    </table>
</div>

<div class="module">
    <table>
        <caption>Publish rows for pairs no enabled type produces</caption>
        <thead><tr><th>Monitor type</th><th>Entry type</th><th>Calibration</th></tr></thead>
        <tbody>
            {% for row in orphans %}
            <tr><th>{{ row.monitor_type }}</th><td>{{ row.entry_type }}</td><td>{{ row.calibration|default:"(default stage)" }}</td></tr>
            {% empty %}
            <tr><td colspan="3">None.</td></tr>
            {% endfor %}
        </tbody>
    </table>
</div>
{% endblock %}
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `RUN_TESTS camp/apps/reports/tests.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add camp/apps/reports/views.py camp/apps/reports/tests.py camp/templates/admin/reports/pipeline_coverage.html
git commit -m "feat(reports): add pipeline coverage report"
```

---

### Task 5: Verification

- [ ] **Step 1:** `RUN_TESTS camp/apps/reports/tests.py camp/apps/monitors camp/apps/summaries camp/apps/calibrations camp/utils/tests/test_admin_maps.py -q` → all PASS.
- [ ] **Step 2:** `RUN_TESTS camp -q` → all PASS (re-run a failing file alone once if the shared DB is busy).
- [ ] **Step 3:** Confirm the admin index sidebar lists nine reports (the existing `test_admin_index_lists_every_report` covers it) and that the index order is: Network Overview, Coverage and Equity, Coverage by Community, Subscription Stats by County, Fleet Health, Degraded Monitors, Data Completeness, Data Quality Problems, Pipeline Coverage. If the definition order in `views.py` differs, move class blocks (no code changes inside them) and commit `chore(reports): order batch two reports on the index`.
- [ ] **Step 4:** Push: `git push origin feature/admin-reports`.

## Self-review

- **Spec coverage:** §5 Coverage by Community (Task 1, including population fallback, nearest distance, uncovered filter, sort, tiles); §6 Data Completeness (Task 2, windows ending yesterday, entry-type selector, threshold, filters); §7 Data Quality (Task 3, seven checks in order, tiles, filters, county Region containment via Exists); §8 Pipeline Coverage (Task 4, matrix, orphans, unpublished count); §Testing (each task's tests). Ordering and push (Task 5).
- **Placeholders:** none.
- **Type consistency:** `MonitorScopeMixin.monitors()` used by Task 1; `admin_change_url(cls, monitor)` defined in Task 2 and used in Tasks 2–3 (Task 3 depends on Task 2 landing first); `daily_summary` and `make_place` helpers defined in the task that uses them; context keys match the templates.
