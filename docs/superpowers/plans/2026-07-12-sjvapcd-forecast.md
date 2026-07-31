# SJVAPCD Daily Air Quality Forecast Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ingest SJVAPCD's daily air quality forecast feed into a new `Forecast` model, keyed to SJV county `Region`s, and expose it through `/api/2.0/forecasts/` for a frontend map layer.

**Architecture:** A new `camp/apps/forecasts` app follows the existing `camp.apps.hms` pattern (external feed → Huey periodic task → idempotent delete-and-recreate per pull) plus a manual management command wrapper. A new `camp/api/v2/forecasts` package follows the existing `camp.api.v2.hms` pattern (serializer/filter/endpoints/urls) for the read API.

**Tech Stack:** Django 5.2, `django-huey`/`huey` (periodic tasks), `defusedxml` (new dependency, safe XML parsing), `requests` (already a dependency), `django-filter`/`resticus` (API layer), PostGIS via `regions.Region`.

## Global Constraints

- Design source of truth: `docs/superpowers/specs/2026-07-12-sjvapcd-forecast-design.md`.
- Feed URL: `https://ww2.valleyair.org/aqinfo/airstatus.xml`. Updated daily by ~4:30pm Pacific.
- Only the 8 feed zones that map to an existing SJV county `Region` are stored. `Kern (SJV Air Basin portion)` maps to the `Kern County` region. `Sequoia National Park and Forest` has no matching region and is dropped.
- Full history is kept — every daily pull writes new rows, never overwrites past `issued_date` rows. Idempotent per `issued_date` (delete-and-recreate), matching `camp.apps.hms.tasks.fetch_smoke`.
- `pollutant` is a `TextChoices` (`O3`, `PM2.5`). `burn_status`/`burn_status_text` stay plain `CharField` (unconfirmed full value set).
- Use `defusedxml.ElementTree`, not stdlib `xml.etree.ElementTree` (XXE/billion-laughs risk on external XML).
- All commands run inside Docker: `docker compose run --rm test pytest ...`, `docker compose run --rm web python manage.py ...`. Tests use `assert`, not `self.assertX()`. Verbose names use `_()` as first positional arg. No `=` alignment in field definitions.
- Region county names in this codebase are stored with a `" County"` suffix (e.g. `"Fresno County"`, `"Kern County"`) — confirmed against `fixtures/regions.yaml` and `camp/apps/regions/managers.py:SJV_COUNTIES`. `Region.objects.counties()` (a manager **method**, not a property) filters to the 8 SJV county regions.
- **Namespace quirk confirmed by hand-parsing the real feed:** the feed declares both `xmlns:burnStatus="https://ww2.valleyair.org/"` and `xmlns:AQI="https://ww2.valleyair.org/"` — the *same* URI for both prefixes. This means `<burnStatus:today>` and `<AQI:today>` parse to the **identical** Clark-notation tag `{https://ww2.valleyair.org/}today` in `ElementTree`/`defusedxml`. You cannot distinguish them by tag lookup — `item.findall('{https://ww2.valleyair.org/}today')` returns *both* elements (burn status first, then AQI, in document order) under one call. They must be told apart by content shape (AQI text starts with a digit and ends with `(POLLUTANT)`; burn status text does not) — see `split_today_tomorrow()` in Task 2. Do not "fix" this to a per-namespace lookup; it will silently return the wrong element.

---

## File Structure

```
camp/apps/forecasts/
    __init__.py
    apps.py
    models.py
    admin.py
    tasks.py
    tests.py
    management/__init__.py
    management/commands/__init__.py
    management/commands/fetch_forecasts.py
    migrations/__init__.py
    migrations/0001_initial.py       # generated, not hand-written

camp/api/v2/forecasts/
    __init__.py
    serializers.py
    filters.py
    endpoints.py
    urls.py
    tests.py

camp/settings/base.py                # register app in INSTALLED_APPS
camp/api/v2/urls.py                  # mount forecasts app
requirements/base.txt                # add defusedxml
```

---

### Task 1: `forecasts` app scaffold + `Forecast` model + admin

**Files:**
- Create: `camp/apps/forecasts/__init__.py`
- Create: `camp/apps/forecasts/apps.py`
- Create: `camp/apps/forecasts/models.py`
- Create: `camp/apps/forecasts/admin.py`
- Create: `camp/apps/forecasts/migrations/__init__.py`
- Create: `camp/apps/forecasts/migrations/0001_initial.py` (generated via `makemigrations`, not hand-written)
- Create: `camp/apps/forecasts/tests.py`
- Modify: `camp/settings/base.py:107` (INSTALLED_APPS, insert after `'camp.apps.entries',` and before `'camp.apps.helpdesk',`)

**Interfaces:**
- Produces: `camp.apps.forecasts.models.Forecast` — fields `sqid`, `region` (FK to `regions.Region`), `zone_name`, `forecast_date`, `issued_date`, `published_at`, `aqi_value`, `aqi_category`, `pollutant` (`Forecast.Pollutant.OZONE = 'O3'`, `Forecast.Pollutant.PM25 = 'PM2.5'`), `burn_status`, `burn_status_text`, `air_alert`, `air_alert_start`, `air_alert_end`. Task 2's `tasks.py` and Task 4's API both import this model directly.

- [ ] **Step 1: Create the app package skeleton**

```bash
mkdir -p camp/apps/forecasts/migrations
touch camp/apps/forecasts/__init__.py
touch camp/apps/forecasts/migrations/__init__.py
```

`camp/apps/forecasts/apps.py`:

```python
from django.apps import AppConfig


class ForecastsConfig(AppConfig):
    name = 'camp.apps.forecasts'
```

- [ ] **Step 2: Register the app in `INSTALLED_APPS`**

In `camp/settings/base.py`, find this block (around line 106-108):

```python
    'camp.apps.entries',
    'camp.apps.helpdesk',
    'camp.apps.hms',
```

Change it to:

```python
    'camp.apps.entries',
    'camp.apps.forecasts',
    'camp.apps.helpdesk',
    'camp.apps.hms',
```

- [ ] **Step 3: Write the failing model test**

`camp/apps/forecasts/tests.py`:

```python
from datetime import date, datetime, timezone as dt_timezone

from django.test import TestCase

from camp.apps.regions.models import Region

from .models import Forecast


class ForecastModelTests(TestCase):
    fixtures = ['regions.yaml']

    def test_create_forecast(self):
        region = Region.objects.get(name='Fresno County')
        forecast = Forecast.objects.create(
            region=region,
            zone_name='Fresno',
            forecast_date=date(2026, 7, 11),
            issued_date=date(2026, 7, 11),
            published_at=datetime(2026, 7, 11, 21, 31, 9, tzinfo=dt_timezone.utc),
            aqi_value=101,
            aqi_category='Unhealthy for Sensitive Groups',
            pollutant=Forecast.Pollutant.OZONE,
            burn_status='Discouraged',
            burn_status_text='Discouraged: Burning Discouraged',
            air_alert=False,
        )
        assert forecast.sqid
        assert forecast.pollutant == 'O3'
        assert str(forecast) == 'Fresno forecast for 2026-07-11 (issued 2026-07-11)'
        assert Forecast.objects.filter(region=region).count() == 1

    def test_ordering_is_newest_issued_first(self):
        region = Region.objects.get(name='Fresno County')
        older = Forecast.objects.create(
            region=region, zone_name='Fresno',
            forecast_date=date(2026, 7, 10), issued_date=date(2026, 7, 10),
            published_at=datetime(2026, 7, 10, 21, 31, 9, tzinfo=dt_timezone.utc),
            aqi_value=90, aqi_category='Moderate', pollutant=Forecast.Pollutant.OZONE,
            burn_status='Discouraged', burn_status_text='Discouraged: Burning Discouraged',
        )
        newer = Forecast.objects.create(
            region=region, zone_name='Fresno',
            forecast_date=date(2026, 7, 11), issued_date=date(2026, 7, 11),
            published_at=datetime(2026, 7, 11, 21, 31, 9, tzinfo=dt_timezone.utc),
            aqi_value=101, aqi_category='Unhealthy for Sensitive Groups', pollutant=Forecast.Pollutant.OZONE,
            burn_status='Discouraged', burn_status_text='Discouraged: Burning Discouraged',
        )
        assert list(Forecast.objects.all()) == [newer, older]
```

- [ ] **Step 4: Run the test to verify it fails**

Run: `docker compose run --rm test pytest camp/apps/forecasts/tests.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'camp.apps.forecasts.models'` (or similar import error, since `models.py` doesn't exist yet).

- [ ] **Step 5: Write the model**

`camp/apps/forecasts/models.py`:

```python
from django.db import models
from django.utils.translation import gettext_lazy as _

from django_sqids import SqidsField, shuffle_alphabet
from model_utils.models import TimeStampedModel


class Forecast(TimeStampedModel):
    class Pollutant(models.TextChoices):
        OZONE = 'O3', _('Ozone')
        PM25 = 'PM2.5', _('PM2.5')

    sqid = SqidsField(alphabet=shuffle_alphabet('forecasts.Forecast'))

    region = models.ForeignKey(
        'regions.Region',
        on_delete=models.CASCADE,
        related_name='forecasts',
    )
    zone_name = models.CharField(_('zone name'), max_length=64)

    forecast_date = models.DateField(_('forecast date'))
    issued_date = models.DateField(_('issued date'))
    published_at = models.DateTimeField(_('published at'))

    aqi_value = models.PositiveSmallIntegerField(_('AQI value'))
    aqi_category = models.CharField(_('AQI category'), max_length=32)
    pollutant = models.CharField(_('pollutant'), max_length=16, choices=Pollutant.choices)

    burn_status = models.CharField(_('burn status'), max_length=32)
    burn_status_text = models.CharField(_('burn status text'), max_length=255)

    air_alert = models.BooleanField(_('air alert'), default=False)
    air_alert_start = models.DateField(_('air alert start'), null=True, blank=True)
    air_alert_end = models.DateField(_('air alert end'), null=True, blank=True)

    class Meta:
        ordering = ('-issued_date', 'region__name')
        indexes = [
            models.Index(fields=['region', 'forecast_date']),
            models.Index(fields=['issued_date']),
        ]

    def __str__(self):
        return f'{self.zone_name} forecast for {self.forecast_date} (issued {self.issued_date})'
```

- [ ] **Step 6: Generate and run the migration**

Run: `docker compose run --rm web python manage.py makemigrations forecasts`
Expected: `Migrations for 'forecasts': camp/apps/forecasts/migrations/0001_initial.py - Create model Forecast`

Run: `docker compose run --rm web python manage.py migrate forecasts`
Expected: `Applying forecasts.0001_initial... OK`

- [ ] **Step 7: Run the test to verify it passes**

Run: `docker compose run --rm test pytest camp/apps/forecasts/tests.py -v`
Expected: PASS (2 tests)

- [ ] **Step 8: Add the admin**

`camp/apps/forecasts/admin.py`:

```python
from django.contrib import admin

from .models import Forecast


@admin.register(Forecast)
class ForecastAdmin(admin.ModelAdmin):
    date_hierarchy = 'forecast_date'
    list_display = ['zone_name', 'forecast_date', 'issued_date', 'aqi_value', 'aqi_category', 'burn_status', 'air_alert']
    list_filter = ['aqi_category', 'burn_status', 'air_alert']
    readonly_fields = [
        'sqid', 'region', 'zone_name', 'forecast_date', 'issued_date', 'published_at',
        'aqi_value', 'aqi_category', 'pollutant', 'burn_status', 'burn_status_text',
        'air_alert', 'air_alert_start', 'air_alert_end',
    ]
    ordering = ('-issued_date', 'zone_name')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        pass
```

- [ ] **Step 9: Commit**

```bash
git add camp/apps/forecasts/__init__.py camp/apps/forecasts/apps.py camp/apps/forecasts/models.py \
        camp/apps/forecasts/admin.py camp/apps/forecasts/tests.py camp/apps/forecasts/migrations/ \
        camp/settings/base.py
git commit -m "feat(forecasts): add Forecast model and admin"
```

---

### Task 2: Ingestion task (`fetch_forecasts`)

**Files:**
- Modify: `requirements/base.txt` (add `defusedxml==0.7.1`, alphabetically between `delegator.py` and `dpath`)
- Create: `camp/apps/forecasts/tasks.py`
- Modify: `camp/apps/forecasts/tests.py` (append task tests)

**Interfaces:**
- Consumes: `camp.apps.forecasts.models.Forecast` (Task 1), `camp.apps.regions.models.Region` + `Region.objects.counties()` (existing), `camp.utils.aqi.aqi_label` (existing).
- Produces: `camp.apps.forecasts.tasks.fetch_forecasts` — a `db_periodic_task` callable via `fetch_forecasts.call_local()` (no arguments). Task 3's management command calls this directly.

- [ ] **Step 1: Add the `defusedxml` dependency**

In `requirements/base.txt`, find:

```
delegator.py==0.1.1
dpath==2.2.0
```

Change to:

```
defusedxml==0.7.1
delegator.py==0.1.1
dpath==2.2.0
```

Run: `docker compose build web test` (rebuilds images with the new dependency)

- [ ] **Step 2: Write the failing ingestion tests**

Append to `camp/apps/forecasts/tests.py`:

```python
from unittest.mock import Mock, patch

from .tasks import fetch_forecasts


SAMPLE_FEED_XML = b"""<?xml version="1.0" encoding="utf-8"?>
<rss version="2.0"   xmlns:burnStatus="https://ww2.valleyair.org/" xmlns:AQI="https://ww2.valleyair.org/">
<title>SJVAPCD mobile app Status</title>
<subtitle>SJVAPCD Air Quality Information</subtitle>
<link rel="self" href="https://ww2.valleyair.org/aqinfo/AirStatus.xml"/>
<link href="https://ww2.valleyair.org/"/>
<author><name>SJVAPCD</name></author>
<icon>/favicon.ico</icon>
<channel>
<title>Air Quality Status</title>
<description>SJVAPCD Air Quality Status by County</description>
<link>https://ww2.valleyair.org/air-quality-information/real-time-air-advisory-network-raan/real-time-air-monitoring-stations/</link>
<language>en-us</language>
<copyright>Copyright 2013 SJVAPCD</copyright>
<lastBuildDate>2026-07-11T21:31:09 -7:00</lastBuildDate>
<generator>SJVAPCD</generator>
<webMaster>webmaster@valleyair.org</webMaster>
<ttl>1440</ttl>
<item>
<guid>http://www.valleyair.org/aqinfo/San Joaquin</guid>
<title>San Joaquin Air Quality Status</title>
<county>San Joaquin</county>
<burnStatus:today date="2026-07-11T00:00:00 -7:00" status="Discouraged">Discouraged: Burning Discouraged</burnStatus:today>
<AQI:today date="2026-07-11T00:00:00 -7:00" status="Yellow">55 Moderate (PM2.5)</AQI:today>
<burnStatus:tomorrow date="2026-07-12T00:00:00 -7:00" status="Discouraged">Discouraged: Burning Discouraged</burnStatus:tomorrow>
<AQI:tomorrow date="2026-07-12T00:00:00 -7:00" status="Yellow">51 Moderate (O3)</AQI:tomorrow>
<airAlertStatus status="NO" startDate="" endDate=""></airAlertStatus>
<link>https://www.valleyair.org/Programs/RAAN/raan_monitoring_system.htm</link>
<pubdate>2026-07-11T14:31:09 -7:00</pubdate>
</item>
<item>
<guid>http://www.valleyair.org/aqinfo/Stanislaus</guid>
<title>Stanislaus Air Quality Status</title>
<county>Stanislaus</county>
<burnStatus:today date="2026-07-11T00:00:00 -7:00" status="Discouraged">Discouraged: Burning Discouraged</burnStatus:today>
<AQI:today date="2026-07-11T00:00:00 -7:00" status="Yellow">77 Moderate (O3)</AQI:today>
<burnStatus:tomorrow date="2026-07-12T00:00:00 -7:00" status="Discouraged">Discouraged: Burning Discouraged</burnStatus:tomorrow>
<AQI:tomorrow date="2026-07-12T00:00:00 -7:00" status="Yellow">58 Moderate (O3)</AQI:tomorrow>
<airAlertStatus status="NO" startDate="" endDate=""></airAlertStatus>
<link>https://www.valleyair.org/Programs/RAAN/raan_monitoring_system.htm</link>
<pubdate>2026-07-11T14:31:09 -7:00</pubdate>
</item>
<item>
<guid>http://www.valleyair.org/aqinfo/Merced</guid>
<title>Merced Air Quality Status</title>
<county>Merced</county>
<burnStatus:today date="2026-07-11T00:00:00 -7:00" status="Discouraged">Discouraged: Burning Discouraged</burnStatus:today>
<AQI:today date="2026-07-11T00:00:00 -7:00" status="Yellow">80 Moderate (O3)</AQI:today>
<burnStatus:tomorrow date="2026-07-12T00:00:00 -7:00" status="Discouraged">Discouraged: Burning Discouraged</burnStatus:tomorrow>
<AQI:tomorrow date="2026-07-12T00:00:00 -7:00" status="Yellow">61 Moderate (O3)</AQI:tomorrow>
<airAlertStatus status="NO" startDate="" endDate=""></airAlertStatus>
<link>https://www.valleyair.org/Programs/RAAN/raan_monitoring_system.htm</link>
<pubdate>2026-07-11T14:31:09 -7:00</pubdate>
</item>
<item>
<guid>http://www.valleyair.org/aqinfo/Madera</guid>
<title>Madera Air Quality Status</title>
<county>Madera</county>
<burnStatus:today date="2026-07-11T00:00:00 -7:00" status="Discouraged">Discouraged: Burning Discouraged</burnStatus:today>
<AQI:today date="2026-07-11T00:00:00 -7:00" status="Yellow">100 Moderate (O3)</AQI:today>
<burnStatus:tomorrow date="2026-07-12T00:00:00 -7:00" status="Discouraged">Discouraged: Burning Discouraged</burnStatus:tomorrow>
<AQI:tomorrow date="2026-07-12T00:00:00 -7:00" status="Yellow">80 Moderate (O3)</AQI:tomorrow>
<airAlertStatus status="NO" startDate="" endDate=""></airAlertStatus>
<link>https://www.valleyair.org/Programs/RAAN/raan_monitoring_system.htm</link>
<pubdate>2026-07-11T14:31:09 -7:00</pubdate>
</item>
<item>
<guid>http://www.valleyair.org/aqinfo/Fresno</guid>
<title>Fresno Air Quality Status</title>
<county>Fresno</county>
<burnStatus:today date="2026-07-11T00:00:00 -7:00" status="Discouraged">Discouraged: Burning Discouraged</burnStatus:today>
<AQI:today date="2026-07-11T00:00:00 -7:00" status="Orange">101 Unhealthy for Sensitive Groups (O3)</AQI:today>
<burnStatus:tomorrow date="2026-07-12T00:00:00 -7:00" status="Discouraged">Discouraged: Burning Discouraged</burnStatus:tomorrow>
<AQI:tomorrow date="2026-07-12T00:00:00 -7:00" status="Yellow">100 Moderate (O3)</AQI:tomorrow>
<airAlertStatus status="NO" startDate="" endDate=""></airAlertStatus>
<link>https://www.valleyair.org/Programs/RAAN/raan_monitoring_system.htm</link>
<pubdate>2026-07-11T14:31:09 -7:00</pubdate>
</item>
<item>
<guid>http://www.valleyair.org/aqinfo/Kings</guid>
<title>Kings Air Quality Status</title>
<county>Kings</county>
<burnStatus:today date="2026-07-11T00:00:00 -7:00" status="Discouraged">Discouraged: Burning Discouraged</burnStatus:today>
<AQI:today date="2026-07-11T00:00:00 -7:00" status="Yellow">71 Moderate (O3)</AQI:today>
<burnStatus:tomorrow date="2026-07-12T00:00:00 -7:00" status="Discouraged">Discouraged: Burning Discouraged</burnStatus:tomorrow>
<AQI:tomorrow date="2026-07-12T00:00:00 -7:00" status="Yellow">53 Moderate (PM2.5)</AQI:tomorrow>
<airAlertStatus status="NO" startDate="" endDate=""></airAlertStatus>
<link>https://www.valleyair.org/Programs/RAAN/raan_monitoring_system.htm</link>
<pubdate>2026-07-11T14:31:09 -7:00</pubdate>
</item>
<item>
<guid>http://www.valleyair.org/aqinfo/Tulare</guid>
<title>Tulare Air Quality Status</title>
<county>Tulare</county>
<burnStatus:today date="2026-07-11T00:00:00 -7:00" status="Discouraged">Discouraged: Burning Discouraged</burnStatus:today>
<AQI:today date="2026-07-11T00:00:00 -7:00" status="Orange">105 Unhealthy for Sensitive Groups (O3)</AQI:today>
<burnStatus:tomorrow date="2026-07-12T00:00:00 -7:00" status="Discouraged">Discouraged: Burning Discouraged</burnStatus:tomorrow>
<AQI:tomorrow date="2026-07-12T00:00:00 -7:00" status="Yellow">84 Moderate (O3)</AQI:tomorrow>
<airAlertStatus status="NO" startDate="" endDate=""></airAlertStatus>
<link>https://www.valleyair.org/Programs/RAAN/raan_monitoring_system.htm</link>
<pubdate>2026-07-11T14:31:09 -7:00</pubdate>
</item>
<item>
<guid>http://www.valleyair.org/aqinfo/Kern (SJV Air Basin portion)</guid>
<title>Kern (SJV Air Basin portion) Air Quality Status</title>
<county>Kern (SJV Air Basin portion)</county>
<burnStatus:today date="2026-07-11T00:00:00 -7:00" status="Discouraged">Discouraged: Burning Discouraged</burnStatus:today>
<AQI:today date="2026-07-11T00:00:00 -7:00" status="Orange">115 Unhealthy for Sensitive Groups (O3)</AQI:today>
<burnStatus:tomorrow date="2026-07-12T00:00:00 -7:00" status="Discouraged">Discouraged: Burning Discouraged</burnStatus:tomorrow>
<AQI:tomorrow date="2026-07-12T00:00:00 -7:00" status="Yellow">100 Moderate (O3)</AQI:tomorrow>
<airAlertStatus status="NO" startDate="" endDate=""></airAlertStatus>
<link>https://www.valleyair.org/Programs/RAAN/raan_monitoring_system.htm</link>
<pubdate>2026-07-11T14:31:09 -7:00</pubdate>
</item>
<item>
<guid>http://www.valleyair.org/aqinfo/Sequoia National Park and Forest</guid>
<title>Sequoia National Park and Forest Air Quality Status</title>
<county>Sequoia National Park and Forest</county>
<burnStatus:today date="2026-07-11T00:00:00 -7:00" status="Discouraged">Discouraged: Burning Discouraged</burnStatus:today>
<AQI:today date="2026-07-11T00:00:00 -7:00" status="Orange">129 Unhealthy for Sensitive Groups (O3)</AQI:today>
<burnStatus:tomorrow date="2026-07-12T00:00:00 -7:00" status="Discouraged">Discouraged: Burning Discouraged</burnStatus:tomorrow>
<AQI:tomorrow date="2026-07-12T00:00:00 -7:00" status="Yellow">100 Moderate (O3)</AQI:tomorrow>
<airAlertStatus status="NO" startDate="" endDate=""></airAlertStatus>
<link>https://www.valleyair.org/Programs/RAAN/raan_monitoring_system.htm</link>
<pubdate>2026-07-11T14:31:09 -7:00</pubdate>
</item>
</channel>
</rss>
"""


def mock_response(content=SAMPLE_FEED_XML):
    response = Mock()
    response.content = content
    response.raise_for_status = Mock()
    return response


class FetchForecastsTests(TestCase):
    fixtures = ['regions.yaml']

    @patch('camp.apps.forecasts.tasks.requests.get')
    def test_creates_forecast_for_each_mapped_zone(self, mock_get):
        mock_get.return_value = mock_response()
        fetch_forecasts.call_local()
        # 8 mapped zones x 2 horizons (today/tomorrow) = 16 rows; Sequoia dropped.
        assert Forecast.objects.count() == 16

    @patch('camp.apps.forecasts.tasks.requests.get')
    def test_skips_unmapped_zone(self, mock_get):
        mock_get.return_value = mock_response()
        fetch_forecasts.call_local()
        assert not Forecast.objects.filter(zone_name='Sequoia National Park and Forest').exists()

    @patch('camp.apps.forecasts.tasks.requests.get')
    def test_kern_alias_maps_to_kern_county_region(self, mock_get):
        mock_get.return_value = mock_response()
        fetch_forecasts.call_local()
        kern = Region.objects.get(name='Kern County')
        forecast = Forecast.objects.get(
            region=kern, zone_name='Kern (SJV Air Basin portion)', forecast_date=date(2026, 7, 11),
        )
        assert forecast.aqi_value == 115
        assert forecast.pollutant == 'O3'

    @patch('camp.apps.forecasts.tasks.requests.get')
    def test_sets_fields_correctly_for_fresno_today(self, mock_get):
        mock_get.return_value = mock_response()
        fetch_forecasts.call_local()
        fresno = Region.objects.get(name='Fresno County')
        forecast = Forecast.objects.get(region=fresno, forecast_date=date(2026, 7, 11))
        assert forecast.aqi_value == 101
        assert forecast.aqi_category == 'Unhealthy for Sensitive Groups'
        assert forecast.pollutant == 'O3'
        assert forecast.burn_status == 'Discouraged'
        assert forecast.burn_status_text == 'Discouraged: Burning Discouraged'
        assert forecast.air_alert is False
        assert forecast.air_alert_start is None
        assert forecast.air_alert_end is None
        assert forecast.issued_date == date(2026, 7, 11)
        assert forecast.published_at.year == 2026

    @patch('camp.apps.forecasts.tasks.requests.get')
    def test_tomorrow_row_has_next_day_forecast_date(self, mock_get):
        mock_get.return_value = mock_response()
        fetch_forecasts.call_local()
        fresno = Region.objects.get(name='Fresno County')
        forecast = Forecast.objects.get(region=fresno, forecast_date=date(2026, 7, 12))
        assert forecast.aqi_value == 100
        assert forecast.aqi_category == 'Moderate'
        assert forecast.issued_date == date(2026, 7, 11)

    @patch('camp.apps.forecasts.tasks.requests.get')
    def test_pm25_zone_parses_correctly(self, mock_get):
        mock_get.return_value = mock_response()
        fetch_forecasts.call_local()
        san_joaquin = Region.objects.get(name='San Joaquin County')
        forecast = Forecast.objects.get(region=san_joaquin, forecast_date=date(2026, 7, 11))
        assert forecast.pollutant == 'PM2.5'
        assert forecast.aqi_value == 55

    @patch('camp.apps.forecasts.tasks.requests.get')
    def test_idempotent_rerun_does_not_duplicate(self, mock_get):
        mock_get.return_value = mock_response()
        fetch_forecasts.call_local()
        count = Forecast.objects.count()
        assert count == 16
        fetch_forecasts.call_local()
        assert Forecast.objects.count() == count
```

Add `from datetime import date` and `from camp.apps.regions.models import Region` to the existing imports at the top of `camp/apps/forecasts/tests.py` (added in Task 1, `Region` is already imported there — only `date` needs adding alongside the existing `datetime`/`dt_timezone` import).

- [ ] **Step 3: Run the tests to verify they fail**

Run: `docker compose run --rm test pytest camp/apps/forecasts/tests.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'camp.apps.forecasts.tasks'`

- [ ] **Step 4: Write the ingestion task**

`camp/apps/forecasts/tasks.py`:

```python
import re
from datetime import datetime, timedelta, timezone as dt_timezone

import requests
from defusedxml import ElementTree as ET

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django_huey import db_periodic_task
from huey import crontab

from camp.apps.regions.models import Region
from camp.utils.aqi import aqi_label

from .models import Forecast


FEED_URL = 'https://ww2.valleyair.org/aqinfo/airstatus.xml'

# Both the burnStatus: and AQI: prefixes resolve to this same namespace URI in
# the feed, so <burnStatus:today> and <AQI:today> share one Clark-notation tag.
# See split_today_tomorrow() below for how they're told apart.
NAMESPACE_URI = 'https://ww2.valleyair.org/'

# Maps the feed's raw <county> label to the matching county Region's name.
# "Sequoia National Park and Forest" has no matching Region and is skipped.
ZONE_TO_REGION_NAME = {
    'San Joaquin': 'San Joaquin County',
    'Stanislaus': 'Stanislaus County',
    'Merced': 'Merced County',
    'Madera': 'Madera County',
    'Fresno': 'Fresno County',
    'Kings': 'Kings County',
    'Tulare': 'Tulare County',
    'Kern (SJV Air Basin portion)': 'Kern County',
}

# "101 Unhealthy for Sensitive Groups (O3)" -> value=101, pollutant='O3'
AQI_TEXT_RE = re.compile(r'^(\d+)\s+.+?\(([^)]+)\)$')


def parse_feed_datetime(value):
    """Parses feed timestamps like '2026-07-11T14:31:09 -7:00' into aware datetimes."""
    dt_part, offset_part = value.rsplit(' ', 1)
    sign = -1 if offset_part.startswith('-') else 1
    hours_str, minutes_str = offset_part.lstrip('+-').split(':')
    offset = timedelta(hours=int(hours_str), minutes=int(minutes_str)) * sign
    naive = datetime.strptime(dt_part, '%Y-%m-%dT%H:%M:%S')
    return naive.replace(tzinfo=dt_timezone(offset))


def parse_alert_date(value):
    """Parses an air-alert start/end date attribute. Format hasn't been observed
    live (no sample pull has had an active alert); falls back to None on any
    unexpected format rather than breaking ingestion for every zone."""
    if not value:
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except ValueError:
        return None


def parse_aqi_text(text):
    match = AQI_TEXT_RE.match((text or '').strip())
    if not match:
        raise ValueError(f'Unrecognized AQI text: {text!r}')
    return int(match.group(1)), match.group(2)


def split_today_tomorrow(elements):
    """Splits the two same-tag elements for a horizon into (burn_status_el, aqi_el).
    They're told apart by content shape: AQI text matches AQI_TEXT_RE, burn status
    text does not. See the namespace-collision note in tasks.py's module docstring."""
    aqi_el = next(el for el in elements if AQI_TEXT_RE.match((el.text or '').strip()))
    burn_el = next(el for el in elements if el is not aqi_el)
    return burn_el, aqi_el


@db_periodic_task(crontab(minute='45', hour='23,0,1,2'), priority=50)
def fetch_forecasts():
    issued_date = timezone.now().astimezone(settings.DEFAULT_TIMEZONE).date()
    response = requests.get(FEED_URL, timeout=30)
    response.raise_for_status()
    root = ET.fromstring(response.content)

    with transaction.atomic():
        Forecast.objects.filter(issued_date=issued_date).delete()
        for item in root.iter('item'):
            zone_name = (item.findtext('county') or '').strip()
            region_name = ZONE_TO_REGION_NAME.get(zone_name)
            if region_name is None:
                continue  # unmapped zone (e.g. Sequoia National Park and Forest)

            region = Region.objects.counties().filter(name=region_name).first()
            if region is None:
                continue  # region not yet imported

            published_at = parse_feed_datetime(item.findtext('pubdate'))

            alert_el = item.find('airAlertStatus')
            air_alert = alert_el.get('status') == 'YES'
            air_alert_start = parse_alert_date(alert_el.get('startDate'))
            air_alert_end = parse_alert_date(alert_el.get('endDate'))

            for horizon in ('today', 'tomorrow'):
                elements = item.findall(f'{{{NAMESPACE_URI}}}{horizon}')
                burn_el, aqi_el = split_today_tomorrow(elements)

                aqi_value, pollutant = parse_aqi_text(aqi_el.text)
                forecast_date = parse_feed_datetime(aqi_el.get('date')).date()

                Forecast.objects.create(
                    region=region,
                    zone_name=zone_name,
                    forecast_date=forecast_date,
                    issued_date=issued_date,
                    published_at=published_at,
                    aqi_value=aqi_value,
                    aqi_category=aqi_label(aqi_value),
                    pollutant=pollutant,
                    burn_status=burn_el.get('status', ''),
                    burn_status_text=burn_el.text or '',
                    air_alert=air_alert,
                    air_alert_start=air_alert_start,
                    air_alert_end=air_alert_end,
                )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `docker compose run --rm test pytest camp/apps/forecasts/tests.py -v`
Expected: PASS (9 tests total: 2 from Task 1 + 7 new)

- [ ] **Step 6: Commit**

```bash
git add requirements/base.txt camp/apps/forecasts/tasks.py camp/apps/forecasts/tests.py
git commit -m "feat(forecasts): add fetch_forecasts ingestion task"
```

---

### Task 3: Management command

**Files:**
- Create: `camp/apps/forecasts/management/__init__.py`
- Create: `camp/apps/forecasts/management/commands/__init__.py`
- Create: `camp/apps/forecasts/management/commands/fetch_forecasts.py`
- Modify: `camp/apps/forecasts/tests.py` (append command test)

**Interfaces:**
- Consumes: `camp.apps.forecasts.tasks.fetch_forecasts` (Task 2).
- Produces: `manage.py fetch_forecasts` — no arguments.

- [ ] **Step 1: Create the management command package**

```bash
mkdir -p camp/apps/forecasts/management/commands
touch camp/apps/forecasts/management/__init__.py
touch camp/apps/forecasts/management/commands/__init__.py
```

- [ ] **Step 2: Write the failing command test**

Append to `camp/apps/forecasts/tests.py` (add `from django.core.management import call_command` and `from io import StringIO` to the imports):

```python
from io import StringIO

from django.core.management import call_command


class FetchForecastsCommandTests(TestCase):
    fixtures = ['regions.yaml']

    @patch('camp.apps.forecasts.tasks.requests.get')
    def test_command_ingests_forecasts(self, mock_get):
        mock_get.return_value = mock_response()
        out = StringIO()
        call_command('fetch_forecasts', stdout=out)
        assert Forecast.objects.count() == 16
        assert 'Done' in out.getvalue()
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `docker compose run --rm test pytest camp/apps/forecasts/tests.py::FetchForecastsCommandTests -v`
Expected: FAIL — `django.core.management.base.CommandError: Unknown command: 'fetch_forecasts'`

- [ ] **Step 4: Write the command**

`camp/apps/forecasts/management/commands/fetch_forecasts.py`:

```python
from django.core.management.base import BaseCommand

from camp.apps.forecasts.tasks import fetch_forecasts


class Command(BaseCommand):
    help = 'Fetch the SJVAPCD daily air quality forecast feed.'

    def handle(self, *args, **options):
        self.stdout.write('Fetching SJVAPCD forecasts...')
        fetch_forecasts.call_local()
        self.stdout.write(self.style.SUCCESS('Done.'))
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `docker compose run --rm test pytest camp/apps/forecasts/tests.py::FetchForecastsCommandTests -v`
Expected: PASS

- [ ] **Step 6: Run the full app test file**

Run: `docker compose run --rm test pytest camp/apps/forecasts/tests.py -v`
Expected: PASS (10 tests)

- [ ] **Step 7: Commit**

```bash
git add camp/apps/forecasts/management camp/apps/forecasts/tests.py
git commit -m "feat(forecasts): add fetch_forecasts management command"
```

---

### Task 4: API — `/api/2.0/forecasts/`

**Files:**
- Create: `camp/api/v2/forecasts/__init__.py`
- Create: `camp/api/v2/forecasts/serializers.py`
- Create: `camp/api/v2/forecasts/filters.py`
- Create: `camp/api/v2/forecasts/endpoints.py`
- Create: `camp/api/v2/forecasts/urls.py`
- Create: `camp/api/v2/forecasts/tests.py`
- Modify: `camp/api/v2/urls.py`

**Interfaces:**
- Consumes: `camp.apps.forecasts.models.Forecast` (Task 1), `camp.api.v2.regions.serializers.RegionSerializer` (existing).
- Produces: named URLs `api:v2:forecasts:forecast-list` and `api:v2:forecasts:forecast-detail` (kwarg `forecast_id`).

- [ ] **Step 1: Create the package and write the failing API tests**

```bash
mkdir -p camp/api/v2/forecasts
touch camp/api/v2/forecasts/__init__.py
```

`camp/api/v2/forecasts/tests.py`:

```python
from datetime import date, datetime, timezone as dt_timezone

from django.test import TestCase
from django.urls import reverse

from camp.apps.forecasts.models import Forecast
from camp.apps.regions.models import Region


def create_forecast(region, forecast_date, issued_date=None, aqi_value=101,
                     pollutant=Forecast.Pollutant.OZONE, air_alert=False):
    issued_date = issued_date or forecast_date
    return Forecast.objects.create(
        region=region,
        zone_name=region.name.replace(' County', ''),
        forecast_date=forecast_date,
        issued_date=issued_date,
        published_at=datetime(2026, 7, 11, 21, 31, 9, tzinfo=dt_timezone.utc),
        aqi_value=aqi_value,
        aqi_category='Unhealthy for Sensitive Groups',
        pollutant=pollutant,
        burn_status='Discouraged',
        burn_status_text='Discouraged: Burning Discouraged',
        air_alert=air_alert,
    )


class ForecastListTests(TestCase):
    fixtures = ['regions.yaml']

    def setUp(self):
        self.fresno = Region.objects.get(name='Fresno County')
        self.kern = Region.objects.get(name='Kern County')
        self.today = date(2026, 7, 11)
        self.yesterday = date(2026, 7, 10)
        self.tomorrow = date(2026, 7, 12)
        self.forecast_today = create_forecast(self.fresno, self.today)
        self.forecast_tomorrow = create_forecast(self.fresno, self.tomorrow, issued_date=self.today)
        self.forecast_yesterday = create_forecast(self.kern, self.yesterday, issued_date=self.yesterday)
        self.url = reverse('api:v2:forecasts:forecast-list')

    def test_defaults_to_today_and_future(self):
        response = self.client.get(self.url)
        assert response.status_code == 200
        ids = [r['id'] for r in response.json()['data']]
        assert self.forecast_today.sqid in ids
        assert self.forecast_tomorrow.sqid in ids
        assert self.forecast_yesterday.sqid not in ids

    def test_forecast_date_filter_overrides_default(self):
        response = self.client.get(self.url, {'forecast_date': self.yesterday.isoformat()})
        assert response.status_code == 200
        ids = [r['id'] for r in response.json()['data']]
        assert self.forecast_yesterday.sqid in ids
        assert self.forecast_today.sqid not in ids

    def test_region_id_filter(self):
        response = self.client.get(self.url, {
            'region_id': self.kern.sqid,
            'forecast_date__gte': self.yesterday.isoformat(),
        })
        assert response.status_code == 200
        ids = [r['id'] for r in response.json()['data']]
        assert self.forecast_yesterday.sqid in ids
        assert self.forecast_today.sqid not in ids

    def test_response_includes_region_boundary_geometry(self):
        response = self.client.get(self.url)
        data = response.json()['data'][0]
        assert data['region']['boundary'] is not None
        assert 'geometry' in data['region']['boundary']


class ForecastDetailTests(TestCase):
    fixtures = ['regions.yaml']

    def setUp(self):
        self.fresno = Region.objects.get(name='Fresno County')
        self.forecast = create_forecast(self.fresno, date(2026, 7, 11))

    def test_detail(self):
        url = reverse('api:v2:forecasts:forecast-detail', kwargs={'forecast_id': self.forecast.sqid})
        response = self.client.get(url)
        assert response.status_code == 200
        data = response.json()['data']
        assert data['id'] == self.forecast.sqid
        assert data['aqi_value'] == 101
        assert data['pollutant'] == 'O3'

    def test_detail_not_found(self):
        url = reverse('api:v2:forecasts:forecast-detail', kwargs={'forecast_id': 'doesnotexist'})
        response = self.client.get(url)
        assert response.status_code == 404
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `docker compose run --rm test pytest camp/api/v2/forecasts/tests.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'camp.apps.forecasts.models'` resolves fine (exists from Task 1), but `django.urls.exceptions.NoReverseMatch: Reverse for 'forecast-list' not found` since the URL isn't registered yet.

- [ ] **Step 3: Write the serializer**

`camp/api/v2/forecasts/serializers.py`:

```python
from resticus import serializers

from camp.api.v2.regions.serializers import RegionSerializer


class ForecastSerializer(serializers.Serializer):
    fields = (
        ('id', lambda f: f.sqid),
        ('region', lambda f: RegionSerializer(f.region).serialize()),
        'zone_name', 'forecast_date', 'issued_date', 'published_at',
        'aqi_value', 'aqi_category', 'pollutant',
        'burn_status', 'burn_status_text',
        'air_alert', 'air_alert_start', 'air_alert_end',
    )
```

- [ ] **Step 4: Write the filter**

`camp/api/v2/forecasts/filters.py`:

```python
import django_filters
from resticus.filters import FilterSet

from camp.apps.forecasts.models import Forecast


class ForecastFilter(FilterSet):
    region_id = django_filters.CharFilter(field_name='region__sqid', lookup_expr='exact')

    class Meta:
        model = Forecast
        fields = {
            'forecast_date': ['exact', 'lt', 'lte', 'gt', 'gte'],
            'issued_date': ['exact', 'lt', 'lte', 'gt', 'gte'],
        }
```

- [ ] **Step 5: Write the endpoints**

`camp/api/v2/forecasts/endpoints.py`:

```python
from django.conf import settings
from django.utils import timezone

from resticus import generics

from camp.apps.forecasts.models import Forecast

from .filters import ForecastFilter
from .serializers import ForecastSerializer


class ForecastMixin:
    model = Forecast
    serializer_class = ForecastSerializer
    paginate = True

    def get_queryset(self):
        return super().get_queryset().select_related('region', 'region__boundary')


class ForecastList(ForecastMixin, generics.ListEndpoint):
    """List SJVAPCD daily air quality forecasts. Defaults to current and future
    forecasts (forecast_date >= today) unless forecast_date is explicitly filtered."""

    filter_class = ForecastFilter

    def get_queryset(self):
        qs = super().get_queryset()
        if 'forecast_date' not in self.request.GET:
            today = timezone.now().astimezone(settings.DEFAULT_TIMEZONE).date()
            qs = qs.filter(forecast_date__gte=today)
        return qs


class ForecastDetail(ForecastMixin, generics.DetailEndpoint):
    """Retrieve a single SJVAPCD forecast record."""
    lookup_field = 'sqid'
    lookup_url_kwarg = 'forecast_id'
```

- [ ] **Step 6: Write the urls and mount them**

`camp/api/v2/forecasts/urls.py`:

```python
from django.urls import path

from . import endpoints

app_name = 'forecasts'

urlpatterns = [
    path('', endpoints.ForecastList.as_view(), name='forecast-list'),
    path('<forecast_id>/', endpoints.ForecastDetail.as_view(), name='forecast-detail'),
]
```

In `camp/api/v2/urls.py`, find:

```python
    path('regions/', include('camp.api.v2.regions.urls', namespace='regions')),
    path('ceidars/', include('camp.api.v2.ceidars.urls', namespace='ceidars')),
```

Change to:

```python
    path('regions/', include('camp.api.v2.regions.urls', namespace='regions')),
    path('ceidars/', include('camp.api.v2.ceidars.urls', namespace='ceidars')),
    path('forecasts/', include('camp.api.v2.forecasts.urls', namespace='forecasts')),
```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `docker compose run --rm test pytest camp/api/v2/forecasts/tests.py -v`
Expected: PASS (6 tests)

- [ ] **Step 8: Run the full test suite**

Run: `docker compose run --rm test pytest -q`
Expected: PASS, no regressions (632 baseline + new tests from this plan)

- [ ] **Step 9: Commit**

```bash
git add camp/api/v2/forecasts camp/api/v2/urls.py
git commit -m "feat(api): add /api/2.0/forecasts/ endpoints"
```

---

## Self-Review Notes

- **Spec coverage:** Model (Task 1) ✓, ingestion task + zone mapping/skip + idempotency (Task 2) ✓, management command (Task 3) ✓, API list/detail/filters/default-date/nested-boundary (Task 4) ✓, admin (Task 1) ✓. Out-of-scope items (accurate zone geometry, notifications, historical backfill) are explicitly not tasked, per spec.
- **Namespace collision:** flagged as a Global Constraint and directly informed `split_today_tomorrow()` in Task 2 — this was discovered by hand-parsing the real feed during planning, not assumed.
- **County naming:** corrected from the design doc's shorthand (`"Fresno"`) to the actual stored form (`"Fresno County"`), verified against `fixtures/regions.yaml` and `SJV_COUNTIES` — `ZONE_TO_REGION_NAME` in Task 2 uses the corrected form throughout.
- **Type consistency:** `Forecast.Pollutant.OZONE`/`PM25` values (`'O3'`/`'PM2.5'`) match `AQI_TEXT_RE`'s captured group exactly, and match every observed value in the real feed sample used for tests. `fetch_forecasts.call_local()` signature (no args) is consistent between Task 2's tests and Task 3's command.
