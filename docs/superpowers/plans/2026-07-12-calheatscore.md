# CalHeatScore Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ingest CalEPA's CalHeatScore ZIP-code-level daily heat risk forecast into a new `camp/apps/calheatscore/` app and expose it through a dedicated `/api/2.0/calheatscore/` endpoint.

**Architecture:** New Django app with one model (`CalHeatScore`, one row per ZIP region + date), an ArcGIS Feature Service client, a daily Huey periodic task that upserts a 7-day rolling forecast for SJV-area ZIP codes, and two resticus list endpoints (all-ZIPs-for-a-date, all-dates-for-one-ZIP).

**Tech Stack:** Django 4.2, GeoDjango/PostGIS, `django_sqids`, `django_huey`/huey, `django_filters` via `resticus.filters.FilterSet`, `resticus` generics/serializers, `requests`, pytest (Django test runner), Docker Compose.

**Reference spec:** `docs/superpowers/specs/2026-07-12-calheatscore-design.md`

## Global Constraints

- All new models use sqids (`django_sqids.SqidsField`), never `SmallUUIDField` — `alphabet=shuffle_alphabet('<app_label>.<ModelName>')`.
- Verbose names use `_()` as the first positional arg: `FloatField(_('Label'), null=True)`.
- Don't align `=` signs in field definitions.
- Tests use plain `assert` statements, not `self.assertFoo()`; use `pytest.raises` for exceptions.
- All tests inherit from Django's `TestCase` and use Django's fixtures system.
- Never `git add -A` — always explicitly list files.
- No `Co-Authored-By` trailer in commit messages (project-specific convention for this repo).
- Timezone is always `America/Los_Angeles` (`settings.DEFAULT_TIMEZONE`); Django's own `TIME_ZONE` is `UTC`, so huey `crontab()` hours are in UTC.
- Run all Django/pytest commands through Docker: `docker compose run --rm test pytest ...`, `docker compose run --rm web python manage.py ...`.
- FK to `regions.Region` uses the string form `'regions.Region'` for the `to` argument (matches `pesticides`/`ceidars` convention) but imports `Region` directly (`from camp.apps.regions.models import Region`) when a `Region.Type.*` choice is needed for `limit_choices_to`.

---

### Task 1: App scaffolding, model, migration, admin

**Files:**
- Create: `camp/apps/calheatscore/__init__.py` (empty)
- Create: `camp/apps/calheatscore/apps.py`
- Create: `camp/apps/calheatscore/models.py`
- Create: `camp/apps/calheatscore/admin.py`
- Create: `camp/apps/calheatscore/migrations/__init__.py` (empty)
- Create: `camp/apps/calheatscore/migrations/0001_initial.py` (generated)
- Create: `fixtures/calheatscore.yaml`
- Create: `camp/apps/calheatscore/tests.py`
- Modify: `camp/settings/base.py` (add to `INSTALLED_APPS`, after `'camp.apps.ces',` at line 109)

**Interfaces:**
- Produces: `camp.apps.calheatscore.models.CalHeatScore` — fields `region` (FK to `regions.Region`), `date` (`DateField`), `score` (`IntegerField`, `CalHeatScore.Score` choices 0–4), `updated_at` (`DateTimeField`, `auto_now`). Unique on `(region, date)`.
- Produces: `CalHeatScore.Score` — `IntegerChoices`: `LOW=0`, `MILD=1`, `MODERATE=2`, `HIGH=3`, `SEVERE=4`.

- [ ] **Step 1: Create the app package**

Create `camp/apps/calheatscore/__init__.py` (empty file) and `camp/apps/calheatscore/apps.py`:

```python
from django.apps import AppConfig


class CalHeatScoreConfig(AppConfig):
    name = 'camp.apps.calheatscore'
    verbose_name = 'CalHeatScore'
```

- [ ] **Step 2: Register the app in `INSTALLED_APPS`**

In `camp/settings/base.py`, add `'camp.apps.calheatscore',` immediately after `'camp.apps.ces',` (currently line 109):

```python
    'camp.apps.hms',
    'camp.apps.ces',
    'camp.apps.calheatscore',
    'camp.apps.ceidars',
```

- [ ] **Step 3: Write the model**

Create `camp/apps/calheatscore/models.py`:

```python
from django.db import models
from django.utils.translation import gettext_lazy as _

from django_sqids import SqidsField, shuffle_alphabet

from camp.apps.regions.models import Region


class CalHeatScore(models.Model):
    class Score(models.IntegerChoices):
        LOW = 0, _('Low')
        MILD = 1, _('Mild')
        MODERATE = 2, _('Moderate')
        HIGH = 3, _('High')
        SEVERE = 4, _('Severe')

    sqid = SqidsField(alphabet=shuffle_alphabet('calheatscore.CalHeatScore'))
    region = models.ForeignKey(
        'regions.Region',
        verbose_name=_('ZIP Code'),
        on_delete=models.CASCADE,
        related_name='heat_scores',
        limit_choices_to={'type': Region.Type.ZIPCODE},
    )
    date = models.DateField(_('Date'))
    score = models.IntegerField(_('Score'), choices=Score.choices)
    updated_at = models.DateTimeField(_('Updated At'), auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['region', 'date'], name='unique_calheatscore_region_date'),
        ]
        ordering = ['-date']
        verbose_name = _('CalHeatScore')
        verbose_name_plural = _('CalHeatScore Records')

    def __str__(self):
        return f'{self.region.external_id} — {self.date} ({self.get_score_display()})'
```

- [ ] **Step 4: Write the admin registration**

Create `camp/apps/calheatscore/admin.py`:

```python
from django.contrib import admin

from .models import CalHeatScore


@admin.register(CalHeatScore)
class CalHeatScoreAdmin(admin.ModelAdmin):
    list_display = ['region', 'date', 'score', 'updated_at']
    list_filter = ['score', 'date']
    search_fields = ['region__external_id', 'region__name']
    readonly_fields = ['region', 'date', 'score', 'updated_at']

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        pass
```

- [ ] **Step 5: Generate the migration**

Run:
```bash
docker compose run --rm web python manage.py makemigrations calheatscore
```
Expected output: `Migrations for 'calheatscore': camp/apps/calheatscore/migrations/0001_initial.py - Create model CalHeatScore`

- [ ] **Step 6: Apply the migration**

Run:
```bash
docker compose run --rm web python manage.py migrate calheatscore
```
Expected output: `Applying calheatscore.0001_initial... OK`

- [ ] **Step 7: Add the test fixture**

Create `fixtures/calheatscore.yaml`. This references the existing real ZIP region already present in `fixtures/regions.yaml` (pk 11, ZIP `93728`, Fresno) rather than fabricating new geometry — that fixture's ZIP boundary genuinely sits inside its Fresno County boundary (pk 3), so it exercises the real SJV-scoping query in later tasks.

```yaml
# References region pk 11 (ZIP 93728) from fixtures/regions.yaml.
# Load both fixtures together: fixtures = ['regions', 'calheatscore']

- model: calheatscore.calheatscore
  pk: 1
  fields:
    region: 11
    date: '2026-07-11'
    score: 2
    updated_at: '2026-07-11T09:00:00Z'

- model: calheatscore.calheatscore
  pk: 2
  fields:
    region: 11
    date: '2026-07-12'
    score: 3
    updated_at: '2026-07-11T09:00:00Z'

- model: calheatscore.calheatscore
  pk: 3
  fields:
    region: 11
    date: '2026-07-13'
    score: 1
    updated_at: '2026-07-11T09:00:00Z'
```

- [ ] **Step 8: Write the failing model tests**

Create `camp/apps/calheatscore/tests.py`:

```python
from django.test import TestCase

from camp.apps.calheatscore.models import CalHeatScore


class CalHeatScoreModelTests(TestCase):
    fixtures = ['regions', 'calheatscore']

    def test_str(self):
        record = CalHeatScore.objects.get(pk=1)
        assert '93728' in str(record)
        assert '2026-07-11' in str(record)
        assert 'Moderate' in str(record)

    def test_score_display(self):
        record = CalHeatScore.objects.get(pk=1)
        assert record.get_score_display() == 'Moderate'

    def test_region_relation(self):
        record = CalHeatScore.objects.get(pk=1)
        assert record.region.external_id == '93728'

    def test_reverse_related_name(self):
        record = CalHeatScore.objects.get(pk=1)
        assert record in record.region.heat_scores.all()

    def test_unique_region_date_constraint(self):
        from django.db import IntegrityError

        with pytest.raises(IntegrityError):
            CalHeatScore.objects.create(region_id=11, date='2026-07-11', score=0)

    def test_ordering_is_newest_first(self):
        records = list(CalHeatScore.objects.filter(region_id=11))
        dates = [r.date for r in records]
        assert dates == sorted(dates, reverse=True)
```

This test file uses `pytest.raises`, so add the import at the top:

```python
import pytest
from django.test import TestCase

from camp.apps.calheatscore.models import CalHeatScore
```

- [ ] **Step 9: Run the tests to verify they pass**

Run:
```bash
docker compose run --rm test pytest camp/apps/calheatscore/tests.py -v
```
Expected: all 6 tests PASS. (`test_unique_region_date_constraint` verifies the constraint added in Step 3 already works — no red/green cycle needed here since the constraint is part of the initial model, not a later addition.)

- [ ] **Step 10: Commit**

```bash
git add camp/apps/calheatscore/__init__.py camp/apps/calheatscore/apps.py \
  camp/apps/calheatscore/models.py camp/apps/calheatscore/admin.py \
  camp/apps/calheatscore/migrations/__init__.py camp/apps/calheatscore/migrations/0001_initial.py \
  camp/apps/calheatscore/tests.py fixtures/calheatscore.yaml camp/settings/base.py
git commit -m "feat(calheatscore): add CalHeatScore model and admin"
```

---

### Task 2: ArcGIS Feature Service client

**Files:**
- Create: `camp/apps/calheatscore/client.py`
- Create: `camp/apps/calheatscore/test_client.py`

**Interfaces:**
- Consumes: nothing from Task 1 (standalone HTTP client).
- Produces: `CalHeatScoreClient` with `.data(zip_codes: Sequence[str]) -> requests.Response` and `.query(zip_codes: Sequence[str]) -> list[dict]`; `CalHeatScoreError` exception; module-level singleton `calheatscore_client`. Task 3 imports `from .client import calheatscore_client, CalHeatScoreError`.

- [ ] **Step 1: Write the failing client tests**

Create `camp/apps/calheatscore/test_client.py`:

```python
from unittest.mock import MagicMock, patch

import pytest
from django.test import TestCase

from camp.apps.calheatscore.client import CalHeatScoreClient, CalHeatScoreError


def make_response(json_result=None, status_code=200):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_result
    response.raise_for_status = MagicMock()
    return response


class CalHeatScoreClientTests(TestCase):
    def setUp(self):
        self.client = CalHeatScoreClient()

    @patch.object(CalHeatScoreClient, 'data')
    def test_query_returns_feature_attributes(self, mock_data):
        mock_data.return_value = make_response(json_result={
            'features': [
                {'attributes': {'ZIP_CODE': '93728', 'DATE': '2026-07-11', 'CHS_Day_0': '2'}},
            ],
        })

        rows = self.client.query(['93728'])

        assert rows == [{'ZIP_CODE': '93728', 'DATE': '2026-07-11', 'CHS_Day_0': '2'}]
        mock_data.assert_called_once_with(['93728'])

    @patch.object(CalHeatScoreClient, 'data')
    def test_query_returns_empty_list_for_empty_input(self, mock_data):
        rows = self.client.query([])

        assert rows == []
        mock_data.assert_not_called()

    @patch.object(CalHeatScoreClient, 'data')
    def test_query_raises_on_error_property(self, mock_data):
        mock_data.return_value = make_response(json_result={
            'error': {'code': 400, 'message': 'Invalid where clause'},
        })

        with pytest.raises(CalHeatScoreError):
            self.client.query(['93728'])

    def test_data_builds_where_clause_and_params(self):
        with patch.object(self.client.session, 'get') as mock_get:
            mock_get.return_value = make_response(json_result={'features': []})
            self.client.data(['93728', '93650'])

        args, kwargs = mock_get.call_args
        assert args[0] == CalHeatScoreClient.url
        params = kwargs['params']
        assert params['where'] == "ZIP_CODE IN ('93728','93650')"
        assert params['returnGeometry'] == 'false'
        assert params['f'] == 'json'
        assert 'CHS_Day_0' in params['outFields']
        assert 'CHS_Day_6' in params['outFields']
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:
```bash
docker compose run --rm test pytest camp/apps/calheatscore/test_client.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'camp.apps.calheatscore.client'`

- [ ] **Step 3: Implement the client**

Create `camp/apps/calheatscore/client.py`:

```python
from typing import Any, Dict, List, Sequence

import requests


class CalHeatScoreError(Exception):
    pass


class CalHeatScoreClient:
    url = (
        'https://services1.arcgis.com/PCHfdHz4GlDNAhBb/arcgis/rest/services/'
        'CalHeatScore_Live_Data_for_API_Use/FeatureServer/0/query'
    )
    fields = ['ZIP_CODE', 'DATE'] + [f'CHS_Day_{day}' for day in range(7)]

    def __init__(self):
        self.session = requests.Session()

    def data(self, zip_codes: Sequence[str]) -> requests.Response:
        where = 'ZIP_CODE IN ({})'.format(','.join(f"'{z}'" for z in zip_codes))
        params = {
            'where': where,
            'outFields': ','.join(self.fields),
            'returnGeometry': 'false',
            'f': 'json',
        }
        return self.session.get(self.url, params=params)

    def query(self, zip_codes: Sequence[str]) -> List[Dict[str, Any]]:
        if not zip_codes:
            return []

        response = self.data(zip_codes)
        response.raise_for_status()
        body = response.json()

        if 'error' in body:
            raise CalHeatScoreError(body['error'])

        return [feature['attributes'] for feature in body.get('features', [])]


calheatscore_client = CalHeatScoreClient()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run:
```bash
docker compose run --rm test pytest camp/apps/calheatscore/test_client.py -v
```
Expected: all 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add camp/apps/calheatscore/client.py camp/apps/calheatscore/test_client.py
git commit -m "feat(calheatscore): add ArcGIS Feature Service client"
```

---

### Task 3: SJV ZIP scoping + daily ingestion task

**Files:**
- Create: `camp/apps/calheatscore/tasks.py`
- Create: `camp/apps/calheatscore/test_tasks.py`

**Interfaces:**
- Consumes: `camp.apps.calheatscore.models.CalHeatScore` (Task 1), `camp.apps.calheatscore.client.calheatscore_client` / `CalHeatScoreError` (Task 2), `camp.apps.regions.models.Region` (`Region.objects.counties()`, `.combined_geometry()`, `RegionQuerySet.intersects()` — all pre-existing).
- Produces: `get_sjv_zip_regions() -> QuerySet[Region]` and `import_calheatscore` (huey periodic task, callable synchronously in tests via `import_calheatscore.call_local()`).

- [ ] **Step 1: Write the failing task tests**

Create `camp/apps/calheatscore/test_tasks.py`:

```python
from datetime import date
from unittest.mock import patch

from django.test import TestCase

from camp.apps.calheatscore.models import CalHeatScore
from camp.apps.calheatscore.tasks import get_sjv_zip_regions, import_calheatscore
from camp.apps.regions.models import Region


FRESNO_ROW = {
    'ZIP_CODE': '93728',
    'DATE': '2026-07-11',
    'CHS_Day_0': '2',
    'CHS_Day_1': '3',
    'CHS_Day_2': '1',
    'CHS_Day_3': '0',
    'CHS_Day_4': '4',
    'CHS_Day_5': '2',
    'CHS_Day_6': '2',
}


class GetSJVZipRegionsTests(TestCase):
    fixtures = ['regions']

    def test_returns_zip_inside_sjv_county(self):
        regions = get_sjv_zip_regions()
        assert regions.filter(external_id='93728').exists()

    def test_excludes_non_zipcode_regions(self):
        regions = get_sjv_zip_regions()
        assert not regions.exclude(type=Region.Type.ZIPCODE).exists()

    def test_empty_when_no_counties_loaded(self):
        Region.objects.filter(type=Region.Type.COUNTY).delete()
        regions = get_sjv_zip_regions()
        assert regions.count() == 0


class ImportCalHeatScoreTests(TestCase):
    fixtures = ['regions']

    @patch('camp.apps.calheatscore.tasks.calheatscore_client')
    def test_creates_seven_days_of_scores(self, mock_client):
        mock_client.query.return_value = [FRESNO_ROW]

        import_calheatscore.call_local()

        scores = CalHeatScore.objects.filter(region__external_id='93728').order_by('date')
        assert scores.count() == 7
        assert scores.first().date == date(2026, 7, 11)
        assert scores.first().score == 2
        assert scores.last().date == date(2026, 7, 17)
        assert scores.last().score == 2

    @patch('camp.apps.calheatscore.tasks.calheatscore_client')
    def test_skips_unknown_zip_codes(self, mock_client):
        mock_client.query.return_value = [{**FRESNO_ROW, 'ZIP_CODE': '00000'}]

        import_calheatscore.call_local()

        assert CalHeatScore.objects.count() == 0

    @patch('camp.apps.calheatscore.tasks.calheatscore_client')
    def test_upserts_existing_rows_instead_of_duplicating(self, mock_client):
        mock_client.query.return_value = [FRESNO_ROW]
        import_calheatscore.call_local()
        assert CalHeatScore.objects.filter(region__external_id='93728').count() == 7

        updated_row = {**FRESNO_ROW, 'CHS_Day_0': '4'}
        mock_client.query.return_value = [updated_row]
        import_calheatscore.call_local()

        scores = CalHeatScore.objects.filter(region__external_id='93728')
        assert scores.count() == 7
        assert scores.get(date=date(2026, 7, 11)).score == 4

    @patch('camp.apps.calheatscore.tasks.calheatscore_client')
    def test_does_not_call_client_when_no_sjv_zip_regions(self, mock_client):
        Region.objects.filter(type=Region.Type.COUNTY).delete()

        import_calheatscore.call_local()

        mock_client.query.assert_not_called()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:
```bash
docker compose run --rm test pytest camp/apps/calheatscore/test_tasks.py -v
```
Expected: FAIL with `ModuleNotFoundError: No module named 'camp.apps.calheatscore.tasks'`

- [ ] **Step 3: Implement the task**

Create `camp/apps/calheatscore/tasks.py`:

```python
from datetime import datetime, timedelta

from django_huey import db_periodic_task, get_queue
from huey import crontab

from camp.apps.regions.models import Region

from .client import calheatscore_client
from .models import CalHeatScore

DAY_FIELDS = [f'CHS_Day_{day}' for day in range(7)]


def get_sjv_zip_regions():
    sjv_geometry = Region.objects.counties().combined_geometry()
    if sjv_geometry is None:
        return Region.objects.none()

    return Region.objects.filter(type=Region.Type.ZIPCODE).intersects(sjv_geometry)


# CalHeatScore refreshes at 5am and 8am Pacific daily. This runs once at
# 16:00 UTC (9am PDT / 8am PST) — close enough across the DST boundary that
# the source has always refreshed by the time this runs.
@db_periodic_task(crontab(minute='0', hour='16'), priority=50)
def import_calheatscore():
    with get_queue('primary').lock_task('import-calheatscore'):
        regions_by_zip = {region.external_id: region for region in get_sjv_zip_regions()}
        if not regions_by_zip:
            return

        rows = calheatscore_client.query(list(regions_by_zip.keys()))
        for row in rows:
            region = regions_by_zip.get(row['ZIP_CODE'])
            if region is None:
                continue

            base_date = datetime.strptime(row['DATE'], '%Y-%m-%d').date()
            for lead, field in enumerate(DAY_FIELDS):
                value = row.get(field)
                if value in (None, ''):
                    continue

                CalHeatScore.objects.update_or_create(
                    region=region,
                    date=base_date + timedelta(days=lead),
                    defaults={'score': int(value)},
                )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run:
```bash
docker compose run --rm test pytest camp/apps/calheatscore/test_tasks.py -v
```
Expected: all 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add camp/apps/calheatscore/tasks.py camp/apps/calheatscore/test_tasks.py
git commit -m "feat(calheatscore): add daily SJV ingestion task"
```

---

### Task 4: API endpoints

**Files:**
- Create: `camp/api/v2/calheatscore/__init__.py` (empty)
- Create: `camp/api/v2/calheatscore/serializers.py`
- Create: `camp/api/v2/calheatscore/filters.py`
- Create: `camp/api/v2/calheatscore/endpoints.py`
- Create: `camp/api/v2/calheatscore/urls.py`
- Create: `camp/api/v2/calheatscore/tests.py`
- Modify: `camp/api/v2/urls.py` (add `calheatscore/` include, after the `calenviroscreen/` line at line 30)

**Interfaces:**
- Consumes: `camp.apps.calheatscore.models.CalHeatScore` (Task 1).
- Produces: URL names `api:v2:calheatscore:calheatscore-list` and `api:v2:calheatscore:calheatscore-by-zip`.

- [ ] **Step 1: Write the failing endpoint tests**

Create `camp/api/v2/calheatscore/tests.py`:

```python
from datetime import date
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone


class CalHeatScoreListTests(TestCase):
    fixtures = ['regions', 'calheatscore']

    def test_defaults_to_today(self):
        with patch.object(timezone, 'now', return_value=timezone.make_aware(
            timezone.datetime(2026, 7, 12, 10, 0, 0)
        )):
            url = reverse('api:v2:calheatscore:calheatscore-list')
            data = self.client.get(url).json()

        assert data['count'] == 1
        assert data['data'][0]['zip_code'] == '93728'
        assert data['data'][0]['score'] == 3
        assert data['data'][0]['score_display'] == 'High'

    def test_explicit_date_overrides_default(self):
        url = reverse('api:v2:calheatscore:calheatscore-list')
        data = self.client.get(url, {'date': '2026-07-13'}).json()

        assert data['count'] == 1
        assert data['data'][0]['score'] == 1

    def test_no_results_for_date_with_no_data(self):
        url = reverse('api:v2:calheatscore:calheatscore-list')
        data = self.client.get(url, {'date': '2099-01-01'}).json()

        assert data['count'] == 0


class CalHeatScoreByZipTests(TestCase):
    fixtures = ['regions', 'calheatscore']

    def test_returns_all_dates_for_zip_newest_first(self):
        url = reverse('api:v2:calheatscore:calheatscore-by-zip', kwargs={'zipcode': '93728'})
        data = self.client.get(url).json()

        assert data['count'] == 3
        dates = [row['date'] for row in data['data']]
        assert dates == ['2026-07-13', '2026-07-12', '2026-07-11']

    def test_empty_for_unknown_zip(self):
        url = reverse('api:v2:calheatscore:calheatscore-by-zip', kwargs={'zipcode': '00000'})
        data = self.client.get(url).json()

        assert data['count'] == 0
```

- [ ] **Step 2: Run the tests to verify they fail**

Run:
```bash
docker compose run --rm test pytest camp/api/v2/calheatscore/tests.py -v
```
Expected: FAIL with `NoReverseMatch` (URL name `api:v2:calheatscore:calheatscore-list` not registered).

- [ ] **Step 3: Write the serializer**

Create `camp/api/v2/calheatscore/serializers.py`:

```python
from resticus import serializers


class CalHeatScoreSerializer(serializers.Serializer):
    fields = (
        ('zip_code', lambda r: r.region.external_id),
        'date',
        'score',
        ('score_display', lambda r: r.get_score_display()),
    )
```

- [ ] **Step 4: Write the filter**

Create `camp/api/v2/calheatscore/filters.py`:

```python
from resticus.filters import FilterSet

from camp.apps.calheatscore.models import CalHeatScore


class CalHeatScoreFilter(FilterSet):
    class Meta:
        model = CalHeatScore
        fields = {
            'date': ['exact', 'gte', 'lte'],
            'score': ['exact', 'gte', 'lte'],
        }
```

- [ ] **Step 5: Write the endpoints**

Create `camp/api/v2/calheatscore/endpoints.py`:

```python
from django.conf import settings
from django.utils import timezone

from resticus import generics

from camp.apps.calheatscore.models import CalHeatScore

from .filters import CalHeatScoreFilter
from .serializers import CalHeatScoreSerializer


class CalHeatScoreList(generics.ListEndpoint):
    """Today's CalHeatScore for every SJV ZIP code (filterable by ?date=)."""

    model = CalHeatScore
    serializer_class = CalHeatScoreSerializer
    filter_class = CalHeatScoreFilter
    paginate = True

    def get_queryset(self):
        queryset = super().get_queryset().select_related('region')
        if 'date' not in self.request.GET:
            today = timezone.now().astimezone(settings.DEFAULT_TIMEZONE).date()
            queryset = queryset.filter(date=today)
        return queryset


class CalHeatScoreByZip(generics.ListEndpoint):
    """All stored CalHeatScore dates (past actuals + forecast) for one ZIP code."""

    model = CalHeatScore
    serializer_class = CalHeatScoreSerializer
    paginate = True

    def get_queryset(self):
        return (
            super().get_queryset()
            .select_related('region')
            .filter(region__external_id=self.kwargs['zipcode'])
        )
```

- [ ] **Step 6: Wire up the URLs**

Create `camp/api/v2/calheatscore/urls.py`:

```python
from django.urls import path

from . import endpoints

app_name = 'calheatscore'

urlpatterns = [
    path('', endpoints.CalHeatScoreList.as_view(), name='calheatscore-list'),
    path('<str:zipcode>/', endpoints.CalHeatScoreByZip.as_view(), name='calheatscore-by-zip'),
]
```

Also create empty `camp/api/v2/calheatscore/__init__.py`.

In `camp/api/v2/urls.py`, add the include immediately after the `calenviroscreen/` line (currently line 30):

```python
    path('calenviroscreen/', include('camp.api.v2.ces.urls', namespace='ces')),
    path('calheatscore/', include('camp.api.v2.calheatscore.urls', namespace='calheatscore')),
    path('regions/', include('camp.api.v2.regions.urls', namespace='regions')),
```

- [ ] **Step 7: Run the tests to verify they pass**

Run:
```bash
docker compose run --rm test pytest camp/api/v2/calheatscore/tests.py -v
```
Expected: all 5 tests PASS.

- [ ] **Step 8: Commit**

```bash
git add camp/api/v2/calheatscore/ camp/api/v2/urls.py
git commit -m "feat(calheatscore): add /api/2.0/calheatscore/ endpoints"
```

---

### Task 5: Full suite verification

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

Run:
```bash
docker compose run --rm test pytest -q
```
Expected: all tests pass (632 pre-existing + the ~15 new tests added in Tasks 1–4), 0 failures.

- [ ] **Step 2: Confirm migrations are consistent**

Run:
```bash
docker compose run --rm web python manage.py makemigrations --check --dry-run
```
Expected: `No changes detected` (exit code 0) — confirms no stray model changes were left unmigrated.

- [ ] **Step 3: Manually exercise the live task once (optional smoke test)**

Run:
```bash
docker compose run --rm web python manage.py shell -c "from camp.apps.calheatscore.tasks import import_calheatscore; import_calheatscore.call_local()"
docker compose run --rm web python manage.py shell -c "from camp.apps.calheatscore.models import CalHeatScore; print(CalHeatScore.objects.count())"
```
Expected: a nonzero count, confirming the live ArcGIS request, SJV ZIP scoping, and upsert logic all work end-to-end against production regions data (not just fixtures). If the count is 0, check whether `regions.Region` ZIP data has been imported in this environment (`import_zipcodes` management command) before treating this as a bug.
