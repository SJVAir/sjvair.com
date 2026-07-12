# Historical "Monitors At" Endpoint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `GET /api/2.0/monitors/<entry_type>/at/` — a time-traveling version of the
existing `current/` endpoint that returns monitor data as of an arbitrary historical
timestamp, optionally filtered by region(s) or a bounding box.

**Architecture:** Three new/generalized `MonitorQuerySet` methods on
`camp/apps/monitors/managers.py` (health-check-as-of, region/bbox geographic
filtering, and historical entry resolution), a new form, and a new endpoint class
parallel to `CurrentData` — but uncached, since every timestamp is a distinct query.

**Tech Stack:** Django, django.contrib.gis (GEOS), django-resticus, pytest/Django
TestCase.

## Global Constraints

- Full design lives at `docs/superpowers/specs/2026-07-06-timelapse-design.md` in the
  sjvair-python repo (this is a cross-repo feature; that spec is the source of truth
  for the overall shape).
- This plan is independently shippable: it adds one endpoint and does not depend on
  the sjvair-python CLI work.
- Match existing conventions exactly: `CurrentData`/`ClosestMonitor` return an empty
  result set (not a 400) when their form is invalid — do the same here rather than
  introducing a new error-response pattern.
- Timezone handling: naive timestamps are assumed to be `settings.DEFAULT_TIMEZONE`
  (`America/Los_Angeles`), matching `TimezoneDateTimeFilter` in
  `camp/api/v2/filters.py` — never assume UTC for naive input.
- Don't touch `MonitorQuerySet.get_active()` — it's built around `LatestEntry`, which
  only ever reflects the true-latest entry and can't answer "was this active as of an
  arbitrary past timestamp." "Active as of" is instead folded into the new
  `with_entry_as_of()` (a monitor with no qualifying entry in the window is simply
  excluded from the result — see Task 3).

---

### Task 1: Generalize health-check filtering to an arbitrary reference time

**Files:**
- Modify: `camp/apps/monitors/managers.py:170-227` (`select_health`, `filter_healthy`)
- Test: `camp/apps/monitors/tests.py`

**Interfaces:**
- Produces: `MonitorQuerySet.select_health(hours=24, min_score=1, threshold=0.8,
  as_of=None)` and `MonitorQuerySet.filter_healthy(hours=24, min_score=1,
  threshold=0.8, as_of=None)` — `as_of` defaults to `timezone.now()`, so all existing
  callers (`CurrentData`) are unaffected.

Today, `select_health` computes `cutoff = timezone.now() - timedelta(hours=hours)` and
counts `HealthCheck` rows with `hour__gte=cutoff`. Because `timezone.now()` is always
the upper bound already, there's no need for an explicit upper bound today. Once we
allow `as_of` to be an arbitrary past timestamp, we must add an explicit
`hour__lte=as_of` bound too — otherwise a "historical" query would silently count
`HealthCheck` rows from *after* the requested timestamp, leaking future information
into a replay.

- [ ] **Step 1: Write the failing test**

Add to `camp/apps/monitors/tests.py` (uses the existing `MonitorTests` class and
`purple-air.yaml` fixture already loaded there):

```python
    def test_filter_healthy_as_of_excludes_future_health_checks(self):
        from camp.apps.qaqc.models import HealthCheck

        monitor = self.get_purpleair()
        as_of = make_aware(datetime(2026, 1, 1, 12, 0))

        # A passing HealthCheck *before* as_of should count...
        HealthCheck.objects.create(monitor=monitor, hour=as_of - timedelta(hours=1), score=3)
        # ...but one *after* as_of must not count toward the as_of query.
        HealthCheck.objects.create(monitor=monitor, hour=as_of + timedelta(hours=1), score=3)

        # threshold=1.0 over 1 hour requires exactly 1 passing check in-window.
        healthy_ids = set(Monitor.objects.filter_healthy(
            hours=1, min_score=1, threshold=1.0, as_of=as_of,
        ).values_list('pk', flat=True))

        assert monitor.pk in healthy_ids

        # Now push as_of back before either HealthCheck exists — should be excluded.
        earlier = as_of - timedelta(hours=3)
        healthy_ids = set(Monitor.objects.filter_healthy(
            hours=1, min_score=1, threshold=1.0, as_of=earlier,
        ).values_list('pk', flat=True))

        assert monitor.pk not in healthy_ids
```

Add the needed imports at the top of the file if not already present:

```python
from camp.utils.datetime import make_aware
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose run --rm test pytest camp/apps/monitors/tests.py::MonitorTests::test_filter_healthy_as_of_excludes_future_health_checks -v`
Expected: FAIL — `select_health() got an unexpected keyword argument 'as_of'` (or
`filter_healthy()` propagating the same), since the parameter doesn't exist yet.

- [ ] **Step 3: Write minimal implementation**

In `camp/apps/monitors/managers.py`, replace `select_health` and `filter_healthy`:

```python
    def select_health(self, hours: int = 24, min_score: int = 1, threshold: float = 0.8, as_of: Optional[datetime] = None):
        from camp.apps.monitors.models import Monitor
        from camp.apps.qaqc.models import HealthCheck

        as_of = as_of or timezone.now()
        cutoff = as_of - timedelta(hours=hours)
        required_passing = int(hours * threshold)

        passing_count = (
            HealthCheck.objects
            .filter(
                monitor=OuterRef('pk'),
                hour__gte=cutoff,
                hour__lte=as_of,
                score__gte=min_score
            )
            .values('monitor')
            .annotate(count=Count('id'))
            .values('count')[:1]
        )

        whens = []
        for subclass in Monitor.get_subclasses():
            model_name = subclass._meta.model_name
            if getattr(subclass, 'GRADE', None) == Monitor.Grade.LCS:
                whens.append(
                    When(**{
                        f'{model_name}__isnull': False,
                        'passing_health_checks__gte': required_passing,
                    }, then=Value(True))
                )
            else:
                # FEM/FRM monitors
                whens.append(
                    When(**{
                        f'{model_name}__isnull': False
                    }, then=Value(True))
                )

        queryset = self.annotate(
            passing_health_checks=Coalesce(
                Subquery(passing_count, output_field=IntegerField()),
                Value(0),
                output_field=IntegerField(),
            ),
            is_healthy=Case(
                *whens,
                default=Value(False),
                output_field=BooleanField(),
            )
        )

        return queryset

    def filter_healthy(self, hours: int = 24, min_score: int = 1, threshold: float = 0.8, as_of: Optional[datetime] = None):
        return self.select_health(
            hours=hours,
            min_score=min_score,
            threshold=threshold,
            as_of=as_of,
        ).filter(is_healthy=True)
```

(`Optional` and `datetime` are already imported at the top of the file.)

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose run --rm test pytest camp/apps/monitors/tests.py::MonitorTests::test_filter_healthy_as_of_excludes_future_health_checks -v`
Expected: PASS

- [ ] **Step 5: Run the full monitors test suite to check for regressions**

Run: `docker compose run --rm test pytest camp/apps/monitors/tests.py camp/api/v2/monitors/tests/ -v`
Expected: all PASS (in particular `test_current_data` — confirms the `as_of=None`
default preserved live behavior)

- [ ] **Step 6: Commit**

```bash
git add camp/apps/monitors/managers.py camp/apps/monitors/tests.py
git commit -m "feat: generalize health-check filtering to an arbitrary as_of time"
```

---

### Task 2: Region and bounding-box filtering on `MonitorQuerySet`

**Files:**
- Modify: `camp/apps/monitors/managers.py`
- Test: `camp/apps/monitors/tests.py`

**Interfaces:**
- Consumes: `Region.boundary` (nullable `OneToOneField` to `Boundary`),
  `Boundary.geometry` (`MultiPolygonField`), both from
  `camp/apps/regions/models.py`.
- Produces: `MonitorQuerySet.in_regions(regions: Iterable[Region])` and
  `MonitorQuerySet.in_bbox(west: float, south: float, east: float, north: float)`.

- [ ] **Step 1: Write the failing test**

Add to `camp/apps/monitors/tests.py`:

```python
    def _make_region_with_boundary(self, bbox, name='Test Region'):
        from django.contrib.gis.geos import MultiPolygon, Polygon
        from camp.apps.regions.models import Boundary, Region

        region = Region.objects.create(name=name, slug=name.lower().replace(' ', '-'), type=Region.Type.CUSTOM)
        boundary = Boundary.objects.create(
            region=region,
            version='test',
            geometry=MultiPolygon(Polygon.from_bbox(bbox)),
        )
        region.boundary = boundary
        region.save()
        return region

    def test_in_regions_filters_by_covering_boundary(self):
        monitor = self.get_purpleair()
        lon, lat = monitor.position.x, monitor.position.y

        containing = self._make_region_with_boundary(
            (lon - 0.01, lat - 0.01, lon + 0.01, lat + 0.01), name='Containing'
        )
        excluding = self._make_region_with_boundary(
            (lon + 10, lat + 10, lon + 11, lat + 11), name='Excluding'
        )

        assert monitor.pk in set(Monitor.objects.in_regions([containing]).values_list('pk', flat=True))
        assert monitor.pk not in set(Monitor.objects.in_regions([excluding]).values_list('pk', flat=True))
        # Union: covered by *any* of the given regions.
        assert monitor.pk in set(Monitor.objects.in_regions([excluding, containing]).values_list('pk', flat=True))

    def test_in_bbox_filters_by_bounding_box(self):
        monitor = self.get_purpleair()
        lon, lat = monitor.position.x, monitor.position.y

        assert monitor.pk in set(Monitor.objects.in_bbox(lon - 0.01, lat - 0.01, lon + 0.01, lat + 0.01).values_list('pk', flat=True))
        assert monitor.pk not in set(Monitor.objects.in_bbox(lon + 10, lat + 10, lon + 11, lat + 11).values_list('pk', flat=True))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose run --rm test pytest camp/apps/monitors/tests.py::MonitorTests::test_in_regions_filters_by_covering_boundary camp/apps/monitors/tests.py::MonitorTests::test_in_bbox_filters_by_bounding_box -v`
Expected: FAIL — `AttributeError: 'MonitorQuerySet' object has no attribute 'in_regions'`

- [ ] **Step 3: Write minimal implementation**

In `camp/apps/monitors/managers.py`, add to `MonitorQuerySet` (near `get_active`):

```python
    def in_regions(self, regions):
        boundaries = [r.boundary.geometry for r in regions if r.boundary_id]
        if not boundaries:
            return self.none()

        query = Q()
        for geometry in boundaries:
            query |= Q(position__coveredby=geometry)
        return self.filter(query)

    def in_bbox(self, west, south, east, north):
        from django.contrib.gis.geos import Polygon
        bbox = Polygon.from_bbox((west, south, east, north))
        return self.filter(position__within=bbox)
```

(`Q` is already imported at the top of the file.)

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose run --rm test pytest camp/apps/monitors/tests.py::MonitorTests::test_in_regions_filters_by_covering_boundary camp/apps/monitors/tests.py::MonitorTests::test_in_bbox_filters_by_bounding_box -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add camp/apps/monitors/managers.py camp/apps/monitors/tests.py
git commit -m "feat: add region and bbox geographic filters to MonitorQuerySet"
```

---

### Task 3: Resolve each monitor's entry as of a historical timestamp

**Files:**
- Modify: `camp/apps/monitors/managers.py`
- Test: `camp/apps/monitors/tests.py`

**Interfaces:**
- Consumes: `Monitor.get_default_stage(EntryModel)`, `Monitor.get_default_calibration(EntryModel)`
  (both already exist on `Monitor`, `camp/apps/monitors/models.py:282-299`),
  `Monitor.LAST_ACTIVE_LIMIT`.
- Produces: `MonitorQuerySet.with_entry_as_of(entry_model, timestamp, seconds=None) ->
  list[Monitor]`. **Returns a plain `list`, not a queryset** — resolving each
  monitor's default stage/calibration and finding its as-of entry is inherently a
  per-monitor lookup (mirrors the existing per-instance stage resolution in
  `EntryFilterSet`, `camp/api/v2/monitors/filters.py:56-77`), not one bulk SQL query.
  Each returned monitor has `monitor.latest_entry` and
  `monitor.latest_{entry_model.entry_type}` set, matching the attribute names
  `with_latest_entry` already sets — `MonitorSerializer`'s `latest` fixup works
  unchanged against either. Monitors with no qualifying entry are dropped entirely.

- [ ] **Step 1: Write the failing test**

Add to `camp/apps/monitors/tests.py`:

```python
    def test_with_entry_as_of_returns_the_entry_current_at_that_time(self):
        monitor = self.get_purpleair()
        as_of = make_aware(datetime(2026, 1, 1, 12, 0))
        stage = monitor.get_default_stage(entry_models.PM25)

        entry_models.PM25.objects.create(
            monitor_id=monitor.pk, timestamp=as_of - timedelta(minutes=20),
            sensor='a', stage=stage, value=Decimal('9.0'),
        )
        current = entry_models.PM25.objects.create(
            monitor_id=monitor.pk, timestamp=as_of - timedelta(minutes=5),
            sensor='a', stage=stage, value=Decimal('11.0'),
        )
        # An entry *after* as_of must not be picked.
        entry_models.PM25.objects.create(
            monitor_id=monitor.pk, timestamp=as_of + timedelta(minutes=5),
            sensor='a', stage=stage, value=Decimal('99.0'),
        )

        results = Monitor.objects.filter(pk=monitor.pk).with_entry_as_of(entry_models.PM25, as_of)

        assert len(results) == 1
        assert results[0].latest_pm25.pk == current.pk
        assert results[0].latest_entry.pk == current.pk

    def test_with_entry_as_of_drops_monitors_with_no_qualifying_entry(self):
        monitor = self.get_purpleair()
        as_of = make_aware(datetime(2026, 1, 1, 12, 0))

        # Only an entry far outside the active window before as_of.
        stage = monitor.get_default_stage(entry_models.PM25)
        entry_models.PM25.objects.create(
            monitor_id=monitor.pk, timestamp=as_of - timedelta(days=10),
            sensor='a', stage=stage, value=Decimal('9.0'),
        )

        results = Monitor.objects.filter(pk=monitor.pk).with_entry_as_of(
            entry_models.PM25, as_of, seconds=3600,
        )
        assert results == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose run --rm test pytest camp/apps/monitors/tests.py::MonitorTests::test_with_entry_as_of_returns_the_entry_current_at_that_time camp/apps/monitors/tests.py::MonitorTests::test_with_entry_as_of_drops_monitors_with_no_qualifying_entry -v`
Expected: FAIL — `AttributeError: 'MonitorQuerySet' object has no attribute 'with_entry_as_of'`

- [ ] **Step 3: Write minimal implementation**

In `camp/apps/monitors/managers.py`, add to `MonitorQuerySet`:

```python
    def with_entry_as_of(self, entry_model, timestamp, seconds=None):
        entry_type = entry_model.entry_type
        results = []

        for monitor in self:
            window_seconds = seconds if seconds is not None else monitor.LAST_ACTIVE_LIMIT
            cutoff = timestamp - timedelta(seconds=window_seconds)

            stage = monitor.get_default_stage(entry_model)
            lookup = {
                'monitor_id': monitor.pk,
                'timestamp__lte': timestamp,
                'timestamp__gte': cutoff,
                'stage': stage,
            }
            if stage == entry_model.Stage.CALIBRATED:
                lookup['processor'] = monitor.get_default_calibration(entry_model) or ''

            entry = (entry_model.objects
                .filter(**lookup)
                .order_by('-timestamp')
                .first()
            )

            if entry is not None:
                setattr(monitor, f'latest_{entry_type}', entry)
                monitor.latest_entry = entry
                results.append(monitor)

        return results
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose run --rm test pytest camp/apps/monitors/tests.py::MonitorTests::test_with_entry_as_of_returns_the_entry_current_at_that_time camp/apps/monitors/tests.py::MonitorTests::test_with_entry_as_of_drops_monitors_with_no_qualifying_entry -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add camp/apps/monitors/managers.py camp/apps/monitors/tests.py
git commit -m "feat: resolve each monitor's default-stage entry as of a historical timestamp"
```

---

### Task 4: `MonitorAtForm` for validating timestamp/bbox query params

**Files:**
- Create: `camp/api/v2/monitors/forms.py` (add to existing file)
- Test: `camp/api/v2/monitors/tests/test_endpoints.py` (form exercised indirectly via
  the endpoint in Task 5; this task adds a focused unit test alongside it)
- Test: `camp/api/v2/monitors/tests/test_forms.py` (new file)

**Interfaces:**
- Produces: `MonitorAtForm` with `cleaned_data['timestamp']` (tz-aware `datetime`,
  required) and `cleaned_data['bbox']` (`tuple[float, float, float, float]` or
  `None`, optional).

- [ ] **Step 1: Write the failing test**

Create `camp/api/v2/monitors/tests/test_forms.py`:

```python
from datetime import datetime

from django.test import TestCase
from django.utils import timezone

from camp.api.v2.monitors.forms import MonitorAtForm


class MonitorAtFormTests(TestCase):
    def test_requires_timestamp(self):
        form = MonitorAtForm(data={})
        assert not form.is_valid()
        assert 'timestamp' in form.errors

    def test_naive_timestamp_assumed_local(self):
        form = MonitorAtForm(data={'timestamp': '2026-07-04 21:00:00'})
        assert form.is_valid(), form.errors
        assert timezone.is_aware(form.cleaned_data['timestamp'])

    def test_bbox_parses_four_floats(self):
        form = MonitorAtForm(data={
            'timestamp': '2026-07-04T21:00:00Z',
            'bbox': '-120.5,36.0,-119.5,37.0',
        })
        assert form.is_valid(), form.errors
        assert form.cleaned_data['bbox'] == (-120.5, 36.0, -119.5, 37.0)

    def test_bbox_rejects_wrong_number_of_parts(self):
        form = MonitorAtForm(data={
            'timestamp': '2026-07-04T21:00:00Z',
            'bbox': '-120.5,36.0,-119.5',
        })
        assert not form.is_valid()
        assert 'bbox' in form.errors

    def test_bbox_rejects_non_numeric_parts(self):
        form = MonitorAtForm(data={
            'timestamp': '2026-07-04T21:00:00Z',
            'bbox': 'a,b,c,d',
        })
        assert not form.is_valid()
        assert 'bbox' in form.errors

    def test_bbox_optional(self):
        form = MonitorAtForm(data={'timestamp': '2026-07-04T21:00:00Z'})
        assert form.is_valid(), form.errors
        assert form.cleaned_data['bbox'] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose run --rm test pytest camp/api/v2/monitors/tests/test_forms.py -v`
Expected: FAIL — `ModuleNotFoundError` / `ImportError: cannot import name 'MonitorAtForm'`

- [ ] **Step 3: Write minimal implementation**

Add to `camp/api/v2/monitors/forms.py`:

```python
from django import forms
from django.conf import settings
from django.utils import timezone

from camp.utils.datetime import make_aware


class MonitorAtForm(forms.Form):
    timestamp = forms.DateTimeField(required=True)
    bbox = forms.CharField(required=False)

    def clean_timestamp(self):
        value = self.cleaned_data.get('timestamp')
        if value is not None and timezone.is_naive(value):
            value = make_aware(value, tz=settings.DEFAULT_TIMEZONE)
        return value

    def clean_bbox(self):
        value = self.cleaned_data.get('bbox')
        if not value:
            return None

        parts = value.split(',')
        if len(parts) != 4:
            raise forms.ValidationError('bbox must be "west,south,east,north"')

        try:
            return tuple(float(p) for p in parts)
        except ValueError:
            raise forms.ValidationError('bbox values must be numbers')
```

(`EntryExportForm` is already in this file — add `MonitorAtForm` alongside it, don't
replace anything.)

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose run --rm test pytest camp/api/v2/monitors/tests/test_forms.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add camp/api/v2/monitors/forms.py camp/api/v2/monitors/tests/test_forms.py
git commit -m "feat: add MonitorAtForm for validating historical query params"
```

---

### Task 5: `MonitorsAt` endpoint + URL route

**Files:**
- Modify: `camp/api/v2/monitors/endpoints.py`
- Modify: `camp/api/v2/monitors/urls.py`
- Test: `camp/api/v2/monitors/tests/test_endpoints.py`

**Interfaces:**
- Consumes: `MonitorAtForm` (Task 4), `MonitorQuerySet.in_regions`/`in_bbox` (Task 2),
  `MonitorQuerySet.filter_healthy(as_of=...)` (Task 1),
  `MonitorQuerySet.with_entry_as_of` (Task 3), `MonitorMixin`, `EntryTypeMixin`,
  `MonitorSerializer`, `EntrySerializer` (all already in `endpoints.py`/`serializers.py`).
- Produces: `GET /api/2.0/monitors/<entry_type>/at/`, URL name
  `api:v2:monitors:monitor-at`.

- [ ] **Step 1: Write the failing test**

Add to `camp/api/v2/monitors/tests/test_endpoints.py`. First add the view alias near
the top with the others:

```python
monitors_at = endpoints.MonitorsAt.as_view()
```

Then add test methods to `EndpointTests`:

```python
    def test_monitors_at_returns_entry_current_at_timestamp(self):
        monitor = self.get_purple_air()
        as_of = make_aware(datetime(2026, 7, 4, 21, 0))
        stage = monitor.get_default_stage(entry_models.PM25)

        entry = entry_models.PM25.objects.create(
            monitor_id=monitor.pk, timestamp=as_of - timedelta(minutes=5),
            sensor='a', stage=stage, value=Decimal('12.0'),
        )
        entry_models.PM25.objects.create(
            monitor_id=monitor.pk, timestamp=as_of + timedelta(minutes=5),
            sensor='a', stage=stage, value=Decimal('999.0'),
        )

        kwargs = {'entry_type': 'pm25'}
        url = reverse('api:v2:monitors:monitor-at', kwargs=kwargs)
        request = self.factory.get(url, {'timestamp': as_of.isoformat()})
        response = monitors_at(request, **kwargs)
        content = get_response_data(response)

        assert response.status_code == 200
        ids = [m['id'] for m in content['data']]
        assert str(monitor.pk) in ids
        result = next(m for m in content['data'] if m['id'] == str(monitor.pk))
        assert Decimal(str(result['latest']['value'])) == entry.value

    def test_monitors_at_missing_timestamp_returns_empty(self):
        kwargs = {'entry_type': 'pm25'}
        url = reverse('api:v2:monitors:monitor-at', kwargs=kwargs)
        request = self.factory.get(url)  # no timestamp
        response = monitors_at(request, **kwargs)
        content = get_response_data(response)

        assert response.status_code == 200
        assert content['data'] == []

    def test_monitors_at_filters_by_bbox(self):
        monitor = self.get_purple_air()
        as_of = make_aware(datetime(2026, 7, 4, 21, 0))
        stage = monitor.get_default_stage(entry_models.PM25)
        entry_models.PM25.objects.create(
            monitor_id=monitor.pk, timestamp=as_of - timedelta(minutes=5),
            sensor='a', stage=stage, value=Decimal('12.0'),
        )

        lon, lat = monitor.position.x, monitor.position.y
        kwargs = {'entry_type': 'pm25'}
        url = reverse('api:v2:monitors:monitor-at', kwargs=kwargs)

        # bbox far away -> excluded
        request = self.factory.get(url, {
            'timestamp': as_of.isoformat(),
            'bbox': f'{lon + 10},{lat + 10},{lon + 11},{lat + 11}',
        })
        response = monitors_at(request, **kwargs)
        assert get_response_data(response)['data'] == []

        # bbox around the monitor -> included
        request = self.factory.get(url, {
            'timestamp': as_of.isoformat(),
            'bbox': f'{lon - 0.01},{lat - 0.01},{lon + 0.01},{lat + 0.01}',
        })
        response = monitors_at(request, **kwargs)
        ids = [m['id'] for m in get_response_data(response)['data']]
        assert str(monitor.pk) in ids

    def test_monitors_at_bad_region_id_404s(self):
        kwargs = {'entry_type': 'pm25'}
        url = reverse('api:v2:monitors:monitor-at', kwargs=kwargs)
        request = self.factory.get(url, {
            'timestamp': timezone.now().isoformat(),
            'region': 'not-a-real-sqid',
        })
        with self.assertRaises(Http404):
            monitors_at(request, **kwargs)
```

Add `from django.http import Http404` to the test file's imports if not already
present (it currently imports from `django.test`/`django.urls`/`django.utils` only).

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose run --rm test pytest camp/api/v2/monitors/tests/test_endpoints.py -k monitors_at -v`
Expected: FAIL — `AttributeError: module 'camp.api.v2.monitors.endpoints' has no attribute 'MonitorsAt'`

- [ ] **Step 3: Write minimal implementation**

In `camp/api/v2/monitors/endpoints.py`, add the import and the new endpoint class
(place it right after `CurrentData`):

```python
from datetime import timedelta

from camp.apps.regions.models import Region

from .forms import MonitorAtForm
```

(`from datetime import datetime, timedelta` already exists at the top — just confirm
`timedelta` is present; `Region` and `MonitorAtForm` are new imports.)

```python
class MonitorsAt(MonitorMixin, EntryTypeMixin, generics.ListEndpoint):
    """Monitors with data as of an arbitrary historical timestamp. Like current/, but for a specific point in time."""

    form_class = MonitorAtForm
    paginate = False
    serializer_class = MonitorSerializer
    streaming = True

    def get_queryset(self, *args, **kwargs):
        form = self.get_form(self.request.GET)
        if not form.is_valid():
            return []

        timestamp = form.cleaned_data['timestamp']
        bbox = form.cleaned_data.get('bbox')

        queryset = (super()
            .get_queryset(*args, **kwargs)
            .filter(is_hidden=False, position__isnull=False)
        )

        region_ids = self.request.GET.getlist('region')
        if region_ids:
            regions = []
            for region_id in region_ids:
                try:
                    regions.append(Region.objects.get(sqid=region_id))
                except Region.DoesNotExist:
                    raise Http404(f'"{region_id}" is not a valid region id')
            queryset = queryset.in_regions(regions)

        if bbox:
            queryset = queryset.in_bbox(*bbox)

        queryset = queryset.filter_healthy(
            hours=settings.MONITOR_HEALTHY_WINDOW_HOURS,
            threshold=settings.MONITOR_HEALTHY_THRESHOLD,
            as_of=timestamp,
        )

        window_seconds = timedelta(days=settings.MONITOR_ACTIVE_WINDOW_DAYS).total_seconds()
        return queryset.with_entry_as_of(self.entry_model, timestamp, seconds=window_seconds)

    def serialize(self, source, fields=None, include=None, exclude=None, fixup=None):
        include = [('latest', lambda monitor: EntrySerializer(monitor.latest_entry).serialize())]
        return super().serialize(source, fields, include, exclude, fixup)
```

Note `get_queryset` returns a plain `list` here (from `with_entry_as_of`, or `[]` on
invalid form) rather than a `QuerySet`. This is safe: with `paginate = False` and no
`filter_class` set, `resticus.mixins.ListModelMixin.get` passes the list straight
through `filter_queryset`/`paginate_queryset` unchanged (both are no-ops in this
configuration — see `resticus/generics.py:82-111`), and
`resticus.serializers.serialize()` explicitly handles `list` the same as a
`QuerySet` (`resticus/serializers.py:190`, `isinstance(src, (list, set,
models.query.QuerySet))`). No wrapping needed.

In `camp/api/v2/monitors/urls.py`, add the route right after `current-data`:

```python
    path('<entry_type>/at/', endpoints.MonitorsAt.as_view(), name='monitor-at'),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose run --rm test pytest camp/api/v2/monitors/tests/test_endpoints.py -k monitors_at -v`
Expected: PASS. If `ListEndpoint` chokes on a plain list, wrap `with_entry_as_of`'s
result and the `[]` fallback isn't a problem — but the passing-monitors list from
Task 3 may need `list(...)` no-op wrapping only if the endpoint's pagination/streaming
code explicitly calls queryset-only methods; adjust `get_queryset` to convert as
needed and re-run until green.

- [ ] **Step 5: Run the full API test suite to check for regressions**

Run: `docker compose run --rm test pytest camp/api/v2/monitors/ camp/apps/monitors/ -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add camp/api/v2/monitors/endpoints.py camp/api/v2/monitors/urls.py camp/api/v2/monitors/tests/test_endpoints.py
git commit -m "feat: add GET /monitors/<entry_type>/at/ historical current-data endpoint"
```

---

### Task 6: Document the new endpoint in CLAUDE.md

**Files:**
- Modify: `CLAUDE.md:83-91` (API section)

- [ ] **Step 1: Add the new endpoint to the list**

In the "Key v2 endpoints" bullet list in `CLAUDE.md`, add a line after
`GET /api/2.0/monitors/{type}/current/`:

```markdown
- `GET /api/2.0/monitors/{type}/at/` — monitors with data as of a historical timestamp (`?timestamp=`, `?region=`, `?bbox=`)
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: document the historical monitors/at/ endpoint in CLAUDE.md"
```
