# Summaries API Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Regions API (list/detail) and nested summary endpoints for both monitors and regions.

**Architecture:** Two new API modules under `camp/api/v2/` — `regions/` and `summaries/`. Region endpoints follow the existing `hms_smoke` pattern. Summary endpoints share a single `endpoints.py` registered under both `monitors/urls.py` and `regions/urls.py` via separate URL files (no extra namespace — names fall into parent namespace). Resolution is a path extra-dict value, not a URL capture group. Date components narrow the queryset; `SummaryMixin.get_queryset()` is called by subclasses via `super()` so it can layer filters on top of the subject-scoped base queryset.

**Tech Stack:** Django, django-resticus, `camp.apps.summaries.models.{MonitorSummary,RegionSummary}`, `camp.apps.regions.models.Region`, `camp.apps.entries.utils.get_entry_model_by_name`

---

## File Map

**Create:**
- `camp/api/v2/regions/__init__.py`
- `camp/api/v2/regions/serializers.py` — `RegionSerializer` (list, no geometry), `RegionDetailSerializer` (with geometry)
- `camp/api/v2/regions/filters.py` — `RegionFilter` (type)
- `camp/api/v2/regions/endpoints.py` — `RegionList`, `RegionDetail`
- `camp/api/v2/regions/urls.py` — list + detail + include summaries
- `camp/api/v2/regions/tests.py` — region list/detail/filter tests
- `camp/api/v2/summaries/__init__.py`
- `camp/api/v2/summaries/serializers.py` — `MonitorSummarySerializer`, `RegionSummarySerializer`
- `camp/api/v2/summaries/endpoints.py` — `MonitorSummaryList`, `RegionSummaryList`
- `camp/api/v2/summaries/monitor_urls.py` — summary routes nested under monitors
- `camp/api/v2/summaries/region_urls.py` — summary routes nested under regions
- `camp/api/v2/summaries/tests.py` — summary endpoint tests

**Modify:**
- `camp/api/v2/urls.py` — add `regions/` include
- `camp/api/v2/monitors/urls.py` — add `<monitor_id>/summaries/` include

---

## Chunk 1: Regions API

### Task 1: Region serializers and filter

**Files:**
- Create: `camp/api/v2/regions/__init__.py`
- Create: `camp/api/v2/regions/serializers.py`
- Create: `camp/api/v2/regions/filters.py`

- [ ] **Step 1: Create `__init__.py`**

```python
# camp/api/v2/regions/__init__.py
```
(empty file)

- [ ] **Step 2: Write serializers**

```python
# camp/api/v2/regions/serializers.py
from resticus import serializers

from camp.apps.regions.models import Region


class RegionSerializer(serializers.Serializer):
    fields = ['id', 'name', 'type']


class RegionDetailSerializer(serializers.Serializer):
    fields = ['id', 'name', 'type']

    def fixup(self, instance, data):
        data['geometry'] = (
            instance.boundary.geometry.geojson
            if instance.boundary
            else None
        )
        return data
```

- [ ] **Step 3: Write filter**

```python
# camp/api/v2/regions/filters.py
from resticus.filters import FilterSet

from camp.apps.regions.models import Region


class RegionFilter(FilterSet):
    class Meta:
        model = Region
        fields = {'type': ['exact']}
```

---

### Task 2: Region endpoints, URLs, and registration

**Files:**
- Create: `camp/api/v2/regions/endpoints.py`
- Create: `camp/api/v2/regions/urls.py`
- Modify: `camp/api/v2/urls.py`

- [ ] **Step 1: Write endpoints**

```python
# camp/api/v2/regions/endpoints.py
from resticus import generics

from camp.apps.regions.models import Region

from .filters import RegionFilter
from .serializers import RegionDetailSerializer, RegionSerializer


class RegionMixin:
    model = Region
    serializer_class = RegionSerializer

    def get_queryset(self):
        return super().get_queryset().select_related('boundary')


class RegionList(RegionMixin, generics.ListEndpoint):
    filter_class = RegionFilter
    paginate = False


class RegionDetail(RegionMixin, generics.DetailEndpoint):
    serializer_class = RegionDetailSerializer
    lookup_field = 'pk'
    lookup_url_kwarg = 'region_id'
```

- [ ] **Step 2: Write URLs**

```python
# camp/api/v2/regions/urls.py
from django.urls import include, path

from . import endpoints

app_name = 'regions'

urlpatterns = [
    path('', endpoints.RegionList.as_view(), name='region-list'),
    path('<region_id>/', endpoints.RegionDetail.as_view(), name='region-detail'),
    path('<region_id>/summaries/', include('camp.api.v2.summaries.region_urls')),
]
```

Note: the summaries include has **no `namespace=`** — URL names from `region_urls.py` fall into the `regions` namespace automatically.

- [ ] **Step 3: Register in v2 urls.py**

In `camp/api/v2/urls.py`, add after the `hms-smoke` line:

```python
path('regions/', include('camp.api.v2.regions.urls', namespace='regions')),
```

---

### Task 3: Region API tests

**Files:**
- Create: `camp/api/v2/regions/tests.py`

- [ ] **Step 1: Write tests**

```python
# camp/api/v2/regions/tests.py
import pytest

from django.test import TestCase, RequestFactory
from django.urls import reverse

from camp.api.v2.regions.endpoints import RegionDetail, RegionList
from camp.apps.regions.models import Region
from camp.utils.test import get_response_data

region_list = RegionList.as_view()
region_detail = RegionDetail.as_view()

pytestmark = [
    pytest.mark.django_db(transaction=True),
]


class RegionListTests(TestCase):
    fixtures = ['regions.yaml']

    def setUp(self):
        self.factory = RequestFactory()

    def test_list_returns_200(self):
        request = self.factory.get(reverse('api:v2:regions:region-list'))
        response = region_list(request)
        assert response.status_code == 200

    def test_list_has_no_geometry(self):
        request = self.factory.get(reverse('api:v2:regions:region-list'))
        response = region_list(request)
        data = get_response_data(response)
        assert len(data['data']) > 0
        assert 'geometry' not in data['data'][0]

    def test_list_fields(self):
        request = self.factory.get(reverse('api:v2:regions:region-list'))
        response = region_list(request)
        data = get_response_data(response)
        assert set(data['data'][0].keys()) == {'id', 'name', 'type'}

    def test_filter_by_type(self):
        request = self.factory.get(reverse('api:v2:regions:region-list'), {'type': 'county'})
        response = region_list(request)
        data = get_response_data(response)
        assert all(r['type'] == 'county' for r in data['data'])

    def test_filter_by_invalid_type_returns_empty(self):
        request = self.factory.get(reverse('api:v2:regions:region-list'), {'type': 'nonexistent'})
        response = region_list(request)
        data = get_response_data(response)
        assert data['data'] == []


class RegionDetailTests(TestCase):
    fixtures = ['regions.yaml']

    def setUp(self):
        self.factory = RequestFactory()
        self.region = Region.objects.filter(boundary__isnull=False).first()

    def test_detail_returns_200(self):
        request = self.factory.get('/')
        response = region_detail(request, region_id=self.region.pk)
        assert response.status_code == 200

    def test_detail_has_geometry(self):
        request = self.factory.get('/')
        response = region_detail(request, region_id=self.region.pk)
        data = get_response_data(response)
        assert 'geometry' in data['data']
        assert data['data']['geometry'] is not None

    def test_detail_fields(self):
        request = self.factory.get('/')
        response = region_detail(request, region_id=self.region.pk)
        data = get_response_data(response)
        assert set(data['data'].keys()) == {'id', 'name', 'type', 'geometry'}

    def test_detail_null_geometry_for_region_without_boundary(self):
        region = Region.objects.filter(boundary__isnull=True).first()
        if region is None:
            return  # skip: all fixtures have boundaries
        request = self.factory.get('/')
        response = region_detail(request, region_id=region.pk)
        data = get_response_data(response)
        assert data['data']['geometry'] is None
```

- [ ] **Step 2: Run region tests**

```bash
docker compose run --rm test pytest camp/api/v2/regions/tests.py -v
```

Expected: all pass.

- [ ] **Step 3: Commit**

```bash
git add camp/api/v2/regions/ camp/api/v2/urls.py
git commit -m "Add regions API: list with type filter, detail with geometry"
```

---

## Chunk 2: Summary Endpoints

### Task 4: Summary serializers

**Files:**
- Create: `camp/api/v2/summaries/__init__.py`
- Create: `camp/api/v2/summaries/serializers.py`

- [ ] **Step 1: Create `__init__.py`**

```python
# camp/api/v2/summaries/__init__.py
```
(empty file)

- [ ] **Step 2: Write serializers**

```python
# camp/api/v2/summaries/serializers.py
from resticus import serializers


class MonitorSummarySerializer(serializers.Serializer):
    fields = [
        ('timestamp', lambda s: s.timestamp.isoformat()),
        'entry_type',
        'processor',
        'count',
        'expected_count',
        'minimum',
        'maximum',
        'mean',
        'stddev',
        'p25',
        'p75',
        'is_complete',
    ]


class RegionSummarySerializer(serializers.Serializer):
    fields = [
        ('timestamp', lambda s: s.timestamp.isoformat()),
        'entry_type',
        'count',
        'expected_count',
        'minimum',
        'maximum',
        'mean',
        'stddev',
        'p25',
        'p75',
        'is_complete',
        'station_count',
    ]
```

---

### Task 5: Summary endpoints

**Files:**
- Create: `camp/api/v2/summaries/endpoints.py`

**Key design — filter composition:**

`SummaryMixin.get_queryset()` calls `super().get_queryset()` and applies resolution/entry_type/date filters on top. Subclasses call `super().get_queryset()` first (which traverses the MRO: subclass → SummaryMixin → ListEndpoint), then add the subject filter (monitor or region) on the result. This means SummaryMixin gets `Model.objects.all()` from ListEndpoint and applies its filters, then the subclass's `super()` call gets that filtered queryset and narrows it further.

Wait — that's backwards. The MRO call chain is:
- `MonitorSummaryList.get_queryset()` calls `super()` → goes to `SummaryMixin.get_queryset()`
- `SummaryMixin.get_queryset()` calls `super()` → goes to `generics.ListEndpoint.get_queryset()` → returns `MonitorSummary.objects.all()`
- `SummaryMixin` applies resolution/entry_type/date filters → returns narrowed queryset
- `MonitorSummaryList.get_queryset()` gets that back and adds monitor/processor filter

So the correct pattern is:

```python
class MonitorSummaryList(SummaryMixin, generics.ListEndpoint):
    model = MonitorSummary

    def get_queryset(self):
        monitor = ...
        processor = ...
        # super() → SummaryMixin → ListEndpoint → MonitorSummary.objects.all()
        # SummaryMixin filters by resolution/entry_type/date
        # We then filter by monitor/processor on top of that
        return super().get_queryset().filter(monitor=monitor, processor=processor)
```

This is clean, correct, and requires no `self.queryset` hacks.

- [ ] **Step 1: Write endpoints**

```python
# camp/api/v2/summaries/endpoints.py
from resticus import generics

from django.http import Http404
from django.utils.functional import cached_property

from camp.apps.entries.utils import get_entry_model_by_name
from camp.apps.regions.models import Region
from camp.apps.summaries.models import BaseSummary, MonitorSummary, RegionSummary

from .serializers import MonitorSummarySerializer, RegionSummarySerializer


VALID_RESOLUTIONS = {c.value for c in BaseSummary.Resolution}


class SummaryMixin:
    paginate = True
    page_size = 168  # one week of hourly data

    @cached_property
    def resolution(self):
        value = self.kwargs['resolution']
        if value not in VALID_RESOLUTIONS:
            raise Http404(f'"{value}" is not a valid resolution')
        return value

    @cached_property
    def entry_model(self):
        model = get_entry_model_by_name(self.kwargs['entry_type'])
        if model is None:
            raise Http404(f'"{self.kwargs["entry_type"]}" is not a valid entry type')
        return model

    def get_date_filter(self):
        """Build timestamp filter kwargs from optional year/month/day URL kwargs."""
        year = self.kwargs.get('year')
        month = self.kwargs.get('month')
        day = self.kwargs.get('day')
        filters = {}
        if year:
            filters['timestamp__year'] = int(year)
        if month:
            filters['timestamp__month'] = int(month)
        if day:
            filters['timestamp__day'] = int(day)
        return filters

    def get_queryset(self):
        # super() here → generics.ListEndpoint.get_queryset() → self.model.objects.all()
        return super().get_queryset().filter(
            resolution=self.resolution,
            entry_type=self.entry_model.entry_type,
            **self.get_date_filter(),
        ).order_by('timestamp')


class MonitorSummaryList(SummaryMixin, generics.ListEndpoint):
    model = MonitorSummary
    serializer_class = MonitorSummarySerializer

    def get_queryset(self):
        monitor = getattr(self.request, 'monitor', None)
        if monitor is None:
            raise Http404('Monitor not found')
        processor = self.request.GET.get('processor', '')
        # super() → SummaryMixin.get_queryset() → ListEndpoint → MonitorSummary.objects.all()
        # SummaryMixin applies resolution/entry_type/date filters
        # We add monitor/processor on top
        return super().get_queryset().filter(monitor=monitor, processor=processor)


class RegionSummaryList(SummaryMixin, generics.ListEndpoint):
    model = RegionSummary
    serializer_class = RegionSummarySerializer

    def get_queryset(self):
        region_id = self.kwargs.get('region_id')
        try:
            region = Region.objects.get(pk=region_id)
        except Region.DoesNotExist:
            raise Http404('Region not found')
        # super() → SummaryMixin.get_queryset() → ListEndpoint → RegionSummary.objects.all()
        return super().get_queryset().filter(region=region)
```

---

### Task 6: Summary URLs

**Files:**
- Create: `camp/api/v2/summaries/monitor_urls.py`
- Create: `camp/api/v2/summaries/region_urls.py`
- Modify: `camp/api/v2/monitors/urls.py`

`resolution` is passed as an extra dict to `path()` — this puts it in `self.kwargs` on the view but is **not** a URL capture group, so it must **not** appear in `reverse()` calls.

The URL files have **no `app_name`**. They are included without `namespace=` so their URL names fall into the parent namespace (`monitors` or `regions`).

- [ ] **Step 1: Write monitor summary URLs**

```python
# camp/api/v2/summaries/monitor_urls.py
from django.urls import path

from .endpoints import MonitorSummaryList

view = MonitorSummaryList.as_view()

urlpatterns = [
    # hourly
    path('<entry_type>/hourly/<int:year>/', view, {'resolution': 'hour'}, name='monitor-summary-hourly-year'),
    path('<entry_type>/hourly/<int:year>/<int:month>/', view, {'resolution': 'hour'}, name='monitor-summary-hourly-month'),
    path('<entry_type>/hourly/<int:year>/<int:month>/<int:day>/', view, {'resolution': 'hour'}, name='monitor-summary-hourly-day'),

    # daily
    path('<entry_type>/daily/<int:year>/', view, {'resolution': 'day'}, name='monitor-summary-daily-year'),
    path('<entry_type>/daily/<int:year>/<int:month>/', view, {'resolution': 'day'}, name='monitor-summary-daily-month'),

    # coarser resolutions
    path('<entry_type>/monthly/<int:year>/', view, {'resolution': 'month'}, name='monitor-summary-monthly'),
    path('<entry_type>/quarterly/<int:year>/', view, {'resolution': 'quarter'}, name='monitor-summary-quarterly'),
    path('<entry_type>/seasonal/<int:year>/', view, {'resolution': 'season'}, name='monitor-summary-seasonal'),
    path('<entry_type>/yearly/', view, {'resolution': 'year'}, name='monitor-summary-yearly'),
]
```

- [ ] **Step 2: Write region summary URLs**

```python
# camp/api/v2/summaries/region_urls.py
from django.urls import path

from .endpoints import RegionSummaryList

view = RegionSummaryList.as_view()

urlpatterns = [
    # hourly
    path('<entry_type>/hourly/<int:year>/', view, {'resolution': 'hour'}, name='region-summary-hourly-year'),
    path('<entry_type>/hourly/<int:year>/<int:month>/', view, {'resolution': 'hour'}, name='region-summary-hourly-month'),
    path('<entry_type>/hourly/<int:year>/<int:month>/<int:day>/', view, {'resolution': 'hour'}, name='region-summary-hourly-day'),

    # daily
    path('<entry_type>/daily/<int:year>/', view, {'resolution': 'day'}, name='region-summary-daily-year'),
    path('<entry_type>/daily/<int:year>/<int:month>/', view, {'resolution': 'day'}, name='region-summary-daily-month'),

    # coarser resolutions
    path('<entry_type>/monthly/<int:year>/', view, {'resolution': 'month'}, name='region-summary-monthly'),
    path('<entry_type>/quarterly/<int:year>/', view, {'resolution': 'quarter'}, name='region-summary-quarterly'),
    path('<entry_type>/seasonal/<int:year>/', view, {'resolution': 'season'}, name='region-summary-seasonal'),
    path('<entry_type>/yearly/', view, {'resolution': 'year'}, name='region-summary-yearly'),
]
```

- [ ] **Step 3: Register monitor summary URLs**

In `camp/api/v2/monitors/urls.py`, add after the `archive` include line:

```python
path('<monitor_id>/summaries/', include('camp.api.v2.summaries.monitor_urls')),
```

No `namespace=` — names from `monitor_urls.py` fall into the `monitors` namespace.

---

### Task 7: Summary endpoint tests

**Files:**
- Create: `camp/api/v2/summaries/tests.py`

**Important URL note for tests:** When calling views directly via `RequestFactory`, `resolution` is NOT in `reverse()` kwargs (it's not a URL capture group). It IS passed explicitly to the view call. The `_get` helper below handles this correctly.

URL reverse for monitor summaries: `reverse('api:v2:monitors:monitor-summary-hourly-year', kwargs={'monitor_id': pk, 'entry_type': 'pm25', 'year': 2026})`

URL reverse for region summaries: `reverse('api:v2:regions:region-summary-hourly-year', kwargs={'region_id': pk, 'entry_type': 'pm25', 'year': 2026})`

- [ ] **Step 1: Write tests**

```python
# camp/api/v2/summaries/tests.py
from datetime import datetime, timedelta

import pytest

from django.test import TestCase, RequestFactory
from django.urls import reverse
from django.utils import timezone

from camp.api.v2.summaries.endpoints import MonitorSummaryList, RegionSummaryList
from camp.apps.monitors.purpleair.models import PurpleAir
from camp.apps.regions.models import Region
from camp.apps.summaries.models import BaseSummary, MonitorSummary, RegionSummary
from camp.utils.test import get_response_data

monitor_summary_list = MonitorSummaryList.as_view()
region_summary_list = RegionSummaryList.as_view()

pytestmark = [
    pytest.mark.usefixtures('purpleair_monitor'),
    pytest.mark.django_db(transaction=True),
]

# Minimal stats for creating test records
STATS = {
    'count': 30,
    'expected_count': 30,
    'sum_value': 300.0,
    'sum_of_squares': 3000.0,
    'minimum': 10.0,
    'maximum': 10.0,
    'mean': 10.0,
    'stddev': 0.0,
    'p25': 10.0,
    'p75': 10.0,
    'is_complete': True,
    'tdigest': {'C': [], 'n': 0},
}


def make_monitor_summary(monitor, timestamp, resolution='hour', entry_type='pm25', processor=''):
    return MonitorSummary.objects.create(
        monitor=monitor,
        timestamp=timestamp,
        resolution=resolution,
        entry_type=entry_type,
        processor=processor,
        **STATS,
    )


def make_region_summary(region, timestamp, resolution='hour', entry_type='pm25'):
    return RegionSummary.objects.create(
        region=region,
        timestamp=timestamp,
        resolution=resolution,
        entry_type=entry_type,
        station_count=3,
        **STATS,
    )


class MonitorSummaryListTests(TestCase):
    fixtures = ['purple-air.yaml']

    def setUp(self):
        self.factory = RequestFactory()
        self.monitor = PurpleAir.objects.first()
        self.hour = timezone.make_aware(datetime(2026, 3, 15, 10, 0, 0))
        make_monitor_summary(self.monitor, self.hour)

    def _get(self, url_name, entry_type, resolution, year=None, month=None, day=None, query=None):
        """
        Call the monitor summary list view directly.
        url_name: name without 'api:v2:monitors:' prefix
        resolution: passed to the view directly (not in reverse() kwargs — not a URL capture group)
        year/month/day: included in both reverse() kwargs and view kwargs
        """
        reverse_kwargs = {'monitor_id': self.monitor.pk, 'entry_type': entry_type}
        view_kwargs = {'monitor_id': self.monitor.pk, 'entry_type': entry_type, 'resolution': resolution}
        if year is not None:
            reverse_kwargs['year'] = year
            view_kwargs['year'] = year
        if month is not None:
            reverse_kwargs['month'] = month
            view_kwargs['month'] = month
        if day is not None:
            reverse_kwargs['day'] = day
            view_kwargs['day'] = day

        url = reverse(f'api:v2:monitors:{url_name}', kwargs=reverse_kwargs)
        request = self.factory.get(url, query or {})
        request.monitor = self.monitor
        return monitor_summary_list(request, **view_kwargs)

    def test_hourly_year_returns_200(self):
        response = self._get('monitor-summary-hourly-year', 'pm25', 'hour', year=2026)
        assert response.status_code == 200

    def test_year_filter_isolates_records(self):
        make_monitor_summary(self.monitor, timezone.make_aware(datetime(2025, 3, 15, 10, 0, 0)))
        response = self._get('monitor-summary-hourly-year', 'pm25', 'hour', year=2026)
        data = get_response_data(response)
        assert len(data['data']) == 1

    def test_response_fields_no_machinery(self):
        response = self._get('monitor-summary-hourly-year', 'pm25', 'hour', year=2026)
        data = get_response_data(response)
        record = data['data'][0]
        assert 'sum_value' not in record
        assert 'sum_of_squares' not in record
        assert 'tdigest' not in record
        assert 'mean' in record
        assert 'p25' in record
        assert 'p75' in record
        assert 'processor' in record
        assert 'is_complete' in record

    def test_processor_filter_default_empty_string(self):
        make_monitor_summary(self.monitor, self.hour, processor='PM25_EPA_Oct2021')
        response = self._get('monitor-summary-hourly-year', 'pm25', 'hour', year=2026)
        data = get_response_data(response)
        # Default processor='' returns only raw record
        assert len(data['data']) == 1
        assert data['data'][0]['processor'] == ''

    def test_processor_filter_explicit(self):
        make_monitor_summary(self.monitor, self.hour, processor='PM25_EPA_Oct2021')
        response = self._get('monitor-summary-hourly-year', 'pm25', 'hour', year=2026, query={'processor': 'PM25_EPA_Oct2021'})
        data = get_response_data(response)
        assert len(data['data']) == 1
        assert data['data'][0]['processor'] == 'PM25_EPA_Oct2021'

    def test_invalid_entry_type_returns_404(self):
        response = self._get('monitor-summary-hourly-year', 'badtype', 'hour', year=2026)
        assert response.status_code == 404

    def test_ordered_by_timestamp_ascending(self):
        for i in range(1, 4):
            make_monitor_summary(self.monitor, self.hour + timedelta(hours=i))
        response = self._get('monitor-summary-hourly-year', 'pm25', 'hour', year=2026)
        data = get_response_data(response)
        timestamps = [r['timestamp'] for r in data['data']]
        assert timestamps == sorted(timestamps)

    def test_yearly_no_date_returns_all(self):
        make_monitor_summary(self.monitor, timezone.make_aware(datetime(2025, 1, 1)), resolution='year')
        make_monitor_summary(self.monitor, timezone.make_aware(datetime(2026, 1, 1)), resolution='year')
        url = reverse('api:v2:monitors:monitor-summary-yearly', kwargs={
            'monitor_id': self.monitor.pk,
            'entry_type': 'pm25',
        })
        request = self.factory.get(url)
        request.monitor = self.monitor
        response = monitor_summary_list(request, monitor_id=self.monitor.pk, entry_type='pm25', resolution='year')
        data = get_response_data(response)
        assert len(data['data']) == 2

    def test_month_filter(self):
        make_monitor_summary(self.monitor, timezone.make_aware(datetime(2026, 4, 15, 10, 0, 0)))
        response = self._get('monitor-summary-hourly-month', 'pm25', 'hour', year=2026, month=3)
        data = get_response_data(response)
        assert len(data['data']) == 1

    def test_day_filter(self):
        make_monitor_summary(self.monitor, timezone.make_aware(datetime(2026, 3, 16, 10, 0, 0)))
        response = self._get('monitor-summary-hourly-day', 'pm25', 'hour', year=2026, month=3, day=15)
        data = get_response_data(response)
        assert len(data['data']) == 1


class RegionSummaryListTests(TestCase):
    fixtures = ['regions.yaml']

    def setUp(self):
        self.factory = RequestFactory()
        self.region = Region.objects.filter(boundary__isnull=False).first()
        self.hour = timezone.make_aware(datetime(2026, 3, 15, 10, 0, 0))
        make_region_summary(self.region, self.hour)

    def _get(self, url_name, entry_type, resolution, year=None, month=None, day=None, query=None):
        reverse_kwargs = {'region_id': self.region.pk, 'entry_type': entry_type}
        view_kwargs = {'region_id': self.region.pk, 'entry_type': entry_type, 'resolution': resolution}
        if year is not None:
            reverse_kwargs['year'] = year
            view_kwargs['year'] = year
        if month is not None:
            reverse_kwargs['month'] = month
            view_kwargs['month'] = month
        if day is not None:
            reverse_kwargs['day'] = day
            view_kwargs['day'] = day

        url = reverse(f'api:v2:regions:{url_name}', kwargs=reverse_kwargs)
        request = self.factory.get(url, query or {})
        return region_summary_list(request, **view_kwargs)

    def test_hourly_year_returns_200(self):
        response = self._get('region-summary-hourly-year', 'pm25', 'hour', year=2026)
        assert response.status_code == 200

    def test_response_has_station_count(self):
        response = self._get('region-summary-hourly-year', 'pm25', 'hour', year=2026)
        data = get_response_data(response)
        assert 'station_count' in data['data'][0]

    def test_response_has_no_processor(self):
        response = self._get('region-summary-hourly-year', 'pm25', 'hour', year=2026)
        data = get_response_data(response)
        assert 'processor' not in data['data'][0]

    def test_response_fields_no_machinery(self):
        response = self._get('region-summary-hourly-year', 'pm25', 'hour', year=2026)
        data = get_response_data(response)
        record = data['data'][0]
        assert 'sum_value' not in record
        assert 'tdigest' not in record

    def test_invalid_region_returns_404(self):
        request = self.factory.get('/')
        response = region_summary_list(request, region_id='doesnotexist', entry_type='pm25', resolution='hour', year=2026)
        assert response.status_code == 404

    def test_year_filter_isolates_records(self):
        make_region_summary(self.region, timezone.make_aware(datetime(2025, 3, 15, 10, 0, 0)))
        response = self._get('region-summary-hourly-year', 'pm25', 'hour', year=2026)
        data = get_response_data(response)
        assert len(data['data']) == 1

    def test_ordered_by_timestamp_ascending(self):
        for i in range(1, 4):
            make_region_summary(self.region, self.hour + timedelta(hours=i))
        response = self._get('region-summary-hourly-year', 'pm25', 'hour', year=2026)
        data = get_response_data(response)
        timestamps = [r['timestamp'] for r in data['data']]
        assert timestamps == sorted(timestamps)
```

- [ ] **Step 2: Run summary tests**

```bash
docker compose run --rm test pytest camp/api/v2/summaries/tests.py -v
```

Expected: all pass.

- [ ] **Step 3: Commit**

```bash
git add camp/api/v2/summaries/ camp/api/v2/monitors/urls.py
git commit -m "Add summaries API: MonitorSummaryList and RegionSummaryList with date path routing"
```

---

## Chunk 3: Integration

### Task 8: Full test suite

- [ ] **Step 1: Run full test suite**

```bash
docker compose run --rm test pytest -v
```

Expected: all existing tests pass plus new tests.

- [ ] **Step 2: Fix any URL namespace issues**

If `reverse()` raises `NoReverseMatch`:
- Confirm `monitor_urls.py` and `region_urls.py` have **no `app_name`** (they're anonymous includes)
- Confirm the include in `monitors/urls.py` has **no `namespace=`**
- Confirm the include in `regions/urls.py` has **no `namespace=`**

If the region `test_invalid_region_returns_404` fails because resticus returns 500 instead of 404 from `Http404`: wrap the `Region.objects.get()` in the view in a try/except and return `http.Http404()` from resticus instead of raising Django's `Http404`. Check how other endpoints handle missing objects.

- [ ] **Step 3: Commit any fixes**

```bash
git add -p
git commit -m "Fix integration issues in summaries/regions API"
```

---

## Notes for implementor

**`request.monitor`:** Routes under `camp/api/v2/monitors/` have middleware that sets `request.monitor` from `monitor_id`. `MonitorSummaryList` reads from `self.request.monitor` — it's already set. Do not re-fetch.

**`resolution` in URL extra dict:** `path('...', view, {'resolution': 'hour'}, name='...')` puts `resolution` in `self.kwargs['resolution']`. It is NOT a captured group. When reversing URLs in tests, do NOT include `resolution` in the `kwargs` dict passed to `reverse()`. When calling the view directly in tests, DO pass `resolution=` as a kwarg.

**MRO for `get_queryset()`:** `MonitorSummaryList.get_queryset()` calls `super().get_queryset()` which goes to `SummaryMixin.get_queryset()` (since MRO is `MonitorSummaryList → SummaryMixin → generics.ListEndpoint`). `SummaryMixin` calls its own `super().get_queryset()` which hits `ListEndpoint` and returns `Model.objects.all()`. `SummaryMixin` filters that. `MonitorSummaryList` gets that result back from `super()` and adds `.filter(monitor=monitor, processor=processor)`. This chain is correct.

**Resticus pagination response envelope:** `{'data': [...], 'meta': {'page': 1, 'pages': N, 'next': '...', 'previous': '...'}}`. Tests access `data['data']` for records.

**Serializer timestamp format:** `lambda s: s.timestamp.isoformat()` — produces `2026-03-15T10:00:00+00:00` if stored as UTC. To match the entries API which uses `timestamp_local`, consider `s.timestamp.astimezone(settings.DEFAULT_TIMEZONE).isoformat()` if localized output is desired. Either is consistent — just be explicit.
