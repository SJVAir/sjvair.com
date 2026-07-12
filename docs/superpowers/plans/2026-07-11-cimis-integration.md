# CIMIS Weather Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `CIMIS` monitor type that pulls hourly weather station data from California's CIMIS API and stores it as new generic meteorological entry types.

**Architecture:** A hand-rolled `CIMISAPI` client (no third-party CIMIS package — see spec for why) hits the real documented CIMIS REST API (`https://et.water.ca.gov/api/`). Two Huey periodic tasks: one discovers CIMIS stations in San Joaquin Valley counties and creates `CIMIS` monitor records, the other pulls hourly data and creates entries. Ten new generic meteorological entry types are added to `camp/apps/entries/models/`, which is split from a single file into a package as part of this work.

**Tech Stack:** Django, django-huey (Huey task queue), PostGIS (`django.contrib.gis`), `requests`, pytest (via Django `TestCase`).

## Global Constraints

- Tests use plain `assert` statements, not `self.assertFoo()`; use `pytest.raises` for exceptions.
- All tests inherit from Django's `TestCase` and use Django's fixtures system.
- Verbose names use `_()` as first positional arg: `FloatField(_('Label'), null=True)`.
- Don't align `=` signs in field definitions.
- New standalone models (not subclasses of `BaseEntry`/`Monitor`, which inherit their PK field) use sqids (`django_sqids.SqidsField`), not `SmallUUIDField`. `CIMIS` and the new entry types are subclasses of `Monitor`/`BaseEntry` and inherit their PK field automatically — this constraint doesn't create a new choice for this plan, noted for completeness.
- Run tests via `docker compose run --rm test pytest <path> -v`.
- Run management commands via `docker compose run --rm web python manage.py <command>`.
- Never `git add -A` — stage files explicitly.
- No co-authored-by lines in commits.

---

### Task 1: Rename `airnow/client.py` → `airnow/api.py` for naming consistency

Three existing providers split API-client naming between `api.py`/`*API` (`airgradient/api.py` → `AirGradientAPI`, `purpleair/api.py` → `PurpleAirAPI`) and the outlier `airnow/client.py` → `AirNowClient`. Standardize on `api.py`/`*API` before adding a fourth provider.

**Files:**
- Create: `camp/apps/monitors/airnow/api.py` (moved from `client.py`)
- Delete: `camp/apps/monitors/airnow/client.py`
- Modify: `camp/apps/monitors/airnow/tasks.py`
- Modify: `camp/apps/monitors/airnow/tests.py`

**Interfaces:**
- Produces: `camp.apps.monitors.airnow.api.AirNowAPI` (renamed from `AirNowClient`), module-level `camp.apps.monitors.airnow.api.airnow_api` instance (renamed from `camp.apps.monitors.airnow.client.airnow_api`).

- [ ] **Step 1: Confirm the current test suite passes before touching anything**

Run: `docker compose run --rm test pytest camp/apps/monitors/airnow/tests.py -v`
Expected: All tests PASS (baseline before refactor).

- [ ] **Step 2: Move and rename the file**

```bash
git mv camp/apps/monitors/airnow/client.py camp/apps/monitors/airnow/api.py
```

- [ ] **Step 3: Rename the class inside the new file**

In `camp/apps/monitors/airnow/api.py`, change:

```python
class AirNowClient:
```

to:

```python
class AirNowAPI:
```

And change the module-level instantiation at the bottom of the file:

```python
airnow_api = AirNowClient(settings.AIRNOW_API_KEY)
```

to:

```python
airnow_api = AirNowAPI(settings.AIRNOW_API_KEY)
```

- [ ] **Step 4: Update the import in `tasks.py`**

In `camp/apps/monitors/airnow/tasks.py`, change:

```python
from camp.apps.monitors.airnow.client import airnow_api
```

to:

```python
from camp.apps.monitors.airnow.api import airnow_api
```

- [ ] **Step 5: Update `tests.py` — import, instantiation, and all `@patch` targets**

In `camp/apps/monitors/airnow/tests.py`, change the import:

```python
from camp.apps.monitors.airnow.client import AirNowClient
```

to:

```python
from camp.apps.monitors.airnow.api import AirNowAPI
```

Replace every occurrence of `AirNowClient` with `AirNowAPI` (class references and `@patch.object(AirNowClient, ...)` calls), and every string-target patch `'camp.apps.monitors.airnow.client.time.sleep'` with `'camp.apps.monitors.airnow.api.time.sleep'`.

Run this to find every remaining reference after your edits:

```bash
grep -n "AirNowClient\|airnow\.client" camp/apps/monitors/airnow/tests.py
```

Expected: no output.

- [ ] **Step 6: Run the test suite to confirm the rename didn't break anything**

Run: `docker compose run --rm test pytest camp/apps/monitors/airnow/tests.py -v`
Expected: All tests PASS (same tests as Step 1, now against the renamed module).

- [ ] **Step 7: Commit**

```bash
git add camp/apps/monitors/airnow/api.py camp/apps/monitors/airnow/tasks.py camp/apps/monitors/airnow/tests.py
git commit -m "refactor: rename airnow client.py to api.py for naming consistency"
```

Note: `git mv` already staged the deletion of `client.py` and creation of `api.py` as a rename; `git add` on the new path plus the deletion will be picked up together.

---

### Task 2: Split `entries/models.py` into a package

No behavior change — pure reorganization. Verified safe: Django keys models by `app_label.ModelName` not file path (no migration impact), and `camp/apps/monitors/models.py` never imports `camp.apps.entries.models` (only `entries.stages` and `entries.fields`), so there's no circular-import risk in `base.py`.

**Files:**
- Create: `camp/apps/entries/models/__init__.py`
- Create: `camp/apps/entries/models/base.py`
- Create: `camp/apps/entries/models/particulates.py`
- Create: `camp/apps/entries/models/meteorological.py`
- Create: `camp/apps/entries/models/gases.py`
- Delete: `camp/apps/entries/models.py`

**Interfaces:**
- Produces: `camp.apps.entries.models.BaseEntry`, `.PM25`, `.Particulates`, `.PM10`, `.PM100`, `.Temperature`, `.Humidity`, `.Pressure`, `.CO`, `.CO2`, `.NO2`, `.O3`, `.SO2` — same import paths as before (`from camp.apps.entries.models import PM25`, `from camp.apps.entries import models as entry_models; entry_models.PM25`).

- [ ] **Step 1: Confirm the full test suite passes before the split**

Run: `docker compose run --rm test pytest -v`
Expected: All tests PASS (baseline before refactor). This is a full-suite run because this task touches an import path used across 45 files.

- [ ] **Step 2: Create the package directory and move the current file in as `base.py` temporarily**

```bash
mkdir camp/apps/entries/models_pkg
git mv camp/apps/entries/models.py camp/apps/entries/models_pkg/base.py
git mv camp/apps/entries/models_pkg camp/apps/entries/models
```

(Two-step move avoids `models.py` and `models/` colliding mid-operation on case-insensitive filesystems; the intermediate `models_pkg` name only exists for this step.)

- [ ] **Step 3: Split `base.py` into `base.py`, `particulates.py`, `meteorological.py`, `gases.py`**

In `camp/apps/entries/models/base.py`, keep only the imports needed by `BaseEntry` and the `BaseEntry` class itself (everything from the top of the original file through the end of the `BaseEntry` class, i.e. through `get_readings()` — stop before the `# Particulate Matter` comment):

```python
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.contrib.gis.db import models
from django.contrib.postgres.indexes import BrinIndex
from django.utils import timezone
from django.utils.functional import cached_property
from django.utils.translation import gettext_lazy as _

from django_smalluuid.models import SmallUUIDField, uuid_default

from camp.apps.monitors.models import Monitor
from camp.utils import classproperty

from ..levels import LevelSet, AQLevel
from ..managers import EntryQuerySet
from .. import stages


class BaseEntry(models.Model):
    # ... (unchanged — full class body from the original file)
```

Copy the entire `BaseEntry` class body from the original file verbatim (all fields, `Meta`, `classproperty`s, and instance methods through `get_readings()`). Update the two import lines that referenced sibling modules by name (`from . import stages` and `from .levels import LevelSet, AQLevel` and `from .managers import EntryQuerySet`) to the `..` relative form shown above, since `stages.py`, `levels.py`, and `managers.py` now live one level up (in `camp/apps/entries/`, not `camp/apps/entries/models/`).

Create `camp/apps/entries/models/particulates.py`:

```python
from django.contrib.gis.db import models
from django.utils.translation import gettext_lazy as _

from ..levels import LevelSet, AQLevel
from .base import BaseEntry


# Particulate Matter

class PM25(BaseEntry):
    label = _('PM2.5')
    epa_aqs_code = 88101
    units = 'µg/m³'
    summarize = True

    Levels = LevelSet(
        AQLevel.GOOD(0.0),
        AQLevel.MODERATE(9.1),
        AQLevel.UNHEALTHY_SENSITIVE(35.5),
        AQLevel.UNHEALTHY(55.5),
        AQLevel.VERY_UNHEALTHY(150.5),
        AQLevel.HAZARDOUS(250.5),
    )

    value = models.DecimalField(
        max_digits=7, decimal_places=2,
        help_text=_('PM2.5 (µg/m³)'),
    )



class Particulates(BaseEntry):
    label = _('Particulates')
    particles_03um = models.DecimalField(max_digits=8, decimal_places=2, null=True)
    particles_05um = models.DecimalField(max_digits=8, decimal_places=2, null=True)
    particles_10um = models.DecimalField(max_digits=8, decimal_places=2, null=True)
    particles_25um = models.DecimalField(max_digits=8, decimal_places=2, null=True)
    particles_50um = models.DecimalField(max_digits=8, decimal_places=2, null=True)
    particles_100um = models.DecimalField(max_digits=8, decimal_places=2, null=True)


class PM10(BaseEntry):
    label = _('PM1.0')
    units = 'µg/m³'

    value = models.DecimalField(
        max_digits=6, decimal_places=2,
        help_text='PM1.0 (µg/m³)'
    )


class PM100(BaseEntry):
    label = _('PM10.0')
    epa_aqs_code = 81102
    units = 'µg/m³'

    Levels = LevelSet(
        AQLevel.GOOD(0),
        AQLevel.MODERATE(55),
        AQLevel.UNHEALTHY_SENSITIVE(155),
        AQLevel.UNHEALTHY(255),
        AQLevel.VERY_UNHEALTHY(355),
        AQLevel.HAZARDOUS(425),
        AQLevel.VERY_HAZARDOUS(605),
    )

    value = models.DecimalField(
        max_digits=6, decimal_places=2,
        help_text='PM10.0 (µg/m³)'
    )
```

Create `camp/apps/entries/models/meteorological.py` (Temperature/Humidity/Pressure only for this step — the 10 new types are added in Task 3):

```python
from decimal import Decimal, ROUND_HALF_UP

from django.contrib.gis.db import models
from django.utils.translation import gettext_lazy as _

from .base import BaseEntry


# Meteorological

class Temperature(BaseEntry):
    label = _('Temperature')
    epa_aqs_code = 62101
    units = '°F'

    value = models.DecimalField(
        max_digits=4, decimal_places=1,
        help_text=_('Temperature (°F)')
    )

    @property
    def fahrenheit(self):
        return self.value

    @fahrenheit.setter
    def fahrenheit(self, value):
        self.value = value

    @property
    def celsius(self):
        value = (Decimal(self.fahrenheit) - 32) * (Decimal(5) / Decimal(9))
        return value.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)

    @celsius.setter
    def celsius(self, value):
        value = (Decimal(value) * (Decimal(9) / Decimal(5))) + 32
        self.fahrenheit = value.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)


    def serialized_data(self):
        return {
            'temperature_f': self.fahrenheit,
            'temperature_c': self.celsius,
        }


class Humidity(BaseEntry):
    label = _('Humidity')
    epa_aqs_code = 62201
    units = '%'

    value = models.DecimalField(
        max_digits=4, decimal_places=1,
        help_text=_('Relative humidity (%)')
    )


class Pressure(BaseEntry):
    label = _('Atmospheric Pressure')
    units = 'mmHg'

    value = models.DecimalField(
        max_digits=6, decimal_places=2,
        help_text=_('Atmospheric pressure (mmHg)'),
    )

    @property
    def mmhg(self):
        return self.value

    @mmhg.setter
    def mmhg(self, value):
        self.value = Decimal(value).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

    @property
    def hpa(self):
        return (self.mmhg * Decimal('1.33322')).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)

    @hpa.setter
    def hpa(self, value):
        self.mmhg = Decimal(value) / Decimal('1.33322')

    def serialized_data(self):
        return {
            'pressure_mmhg': self.mmhg,
            'pressure_hpa': self.hpa,
        }
```

Create `camp/apps/entries/models/gases.py`:

```python
from django.contrib.gis.db import models
from django.utils.translation import gettext_lazy as _

from ..levels import LevelSet, AQLevel
from .base import BaseEntry


# Gases

class CO(BaseEntry):
    label = _('Carbon Monoxide')
    epa_aqs_code = 42101
    units = 'ppm'
    summarize = True

    Levels = LevelSet(
        AQLevel.GOOD(0.0),
        AQLevel.MODERATE(4.5),
        AQLevel.UNHEALTHY_SENSITIVE(9.5),
        AQLevel.UNHEALTHY(12.5),
        AQLevel.VERY_UNHEALTHY(15.5),
        AQLevel.HAZARDOUS(30.5),
        AQLevel.VERY_HAZARDOUS(50.4),
    )

    value = models.DecimalField(
        max_digits=6, decimal_places=2,
        help_text='Carbon monoxide (ppm)',
    )


class CO2(BaseEntry):
    label = _('Carbon Dioxide')
    epa_aqs_code = 42102
    units = 'ppm'

    value = models.DecimalField(
        max_digits=6, decimal_places=2,
        help_text='Carbon dioxide (ppm)',
    )


class NO2(BaseEntry):
    label = _('Nitrogen Dioxide')
    epa_aqs_code = 42602
    units = 'ppb'
    summarize = True

    Levels = LevelSet(
        AQLevel.GOOD(0.0),
        AQLevel.MODERATE(54.0),
        AQLevel.UNHEALTHY_SENSITIVE(101.0),
        AQLevel.UNHEALTHY(361.0),
        AQLevel.VERY_UNHEALTHY(650.0),
        AQLevel.HAZARDOUS(1250.0),
        AQLevel.VERY_HAZARDOUS(2050.0),
    )

    value = models.DecimalField(
        max_digits=6, decimal_places=2,
        help_text='Nitrogen dioxide (ppb)',
    )


class O3(BaseEntry):
    label = _('Ozone')
    epa_aqs_code = 44201
    units = 'ppb'
    summarize = True

    Levels = LevelSet(
        AQLevel.GOOD(0.0),
        AQLevel.UNHEALTHY_SENSITIVE(125),
        AQLevel.UNHEALTHY(165),
        AQLevel.VERY_UNHEALTHY(205),
        AQLevel.HAZARDOUS(405),
        AQLevel.VERY_HAZARDOUS(605),
    )

    value = models.DecimalField(
        max_digits=6, decimal_places=2,
        help_text='Ozone (ppb)'
    )


class SO2(BaseEntry):
    label = _('Sulfur Dioxide')
    epa_aqs_code = 42401
    units = 'ppb'
    summarize = True

    Levels = LevelSet(
        AQLevel.GOOD(0),
        AQLevel.MODERATE(36),
        AQLevel.UNHEALTHY_SENSITIVE(76),
        AQLevel.UNHEALTHY(186),
        AQLevel.VERY_UNHEALTHY(305),
    )

    value = models.DecimalField(
        max_digits=6, decimal_places=2,
        help_text=_('Sulfur dioxide (ppb)'),
    )
```

- [ ] **Step 4: Create `__init__.py` re-exporting everything**

Create `camp/apps/entries/models/__init__.py`:

```python
from .base import BaseEntry
from .particulates import PM25, Particulates, PM10, PM100
from .meteorological import Temperature, Humidity, Pressure
from .gases import CO, CO2, NO2, O3, SO2
```

- [ ] **Step 5: Run the full test suite to confirm nothing broke**

Run: `docker compose run --rm test pytest -v`
Expected: All tests PASS, same results as Step 1.

- [ ] **Step 6: Run Django's system check and confirm no missing migrations**

Run: `docker compose run --rm web python manage.py makemigrations --check --dry-run`
Expected: `No changes detected` (confirms the split didn't change any model's `app_label`, field definitions, or `Meta`).

- [ ] **Step 7: Commit**

```bash
git add camp/apps/entries/models
git commit -m "refactor: split entries/models.py into a package by entry category"
```

---

### Task 3: Add 10 new meteorological entry types

**Files:**
- Modify: `camp/apps/entries/models/meteorological.py`
- Test: `camp/apps/entries/tests/test_meteorological_entries.py` (create if `camp/apps/entries/tests/` doesn't exist as a package — check first: `ls camp/apps/entries/tests/` or `ls camp/apps/entries/tests.py`)
- Create: `camp/apps/entries/migrations/0004_dewpoint_windspeed_winddirection_precipitation_solarradiation_netradiation_vaporpressure_soiltemperature_eto_etr.py` (actual filename generated by `makemigrations`)

**Interfaces:**
- Produces: `camp.apps.entries.models.DewPoint`, `.WindSpeed`, `.WindDirection`, `.Precipitation`, `.SolarRadiation`, `.NetRadiation`, `.VaporPressure`, `.SoilTemperature`, `.ETo`, `.ETr` — each a `BaseEntry` subclass with a `value` field. `DewPoint` and `SoilTemperature` additionally expose `.fahrenheit`/`.celsius` properties like `Temperature`.

- [ ] **Step 1: Check whether `camp/apps/entries/tests/` exists as a directory or `tests.py` as a file**

Run: `ls camp/apps/entries/ | grep test`
If it's a single `tests.py` file, add the new test class to that file instead of creating `camp/apps/entries/tests/test_meteorological_entries.py`; adjust the remaining steps' file path accordingly.

- [ ] **Step 2: Write the failing tests**

```python
from decimal import Decimal

from django.test import TestCase

from camp.apps.entries import models as entry_models
from camp.apps.monitors.aqview.models import AQview
from django.contrib.gis.geos import Point


class MeteorologicalEntryTests(TestCase):
    def setUp(self):
        self.monitor = AQview.objects.create(
            name='Test Station',
            position=Point(-119.7871, 36.7378, srid=4326),
            location=AQview.LOCATION.outside,
        )

    def test_dew_point_fahrenheit_celsius_conversion(self):
        entry = self.monitor.create_entry(entry_models.DewPoint, timestamp=self.monitor.created, value=Decimal('50.0'))
        assert entry.fahrenheit == Decimal('50.0')
        assert entry.celsius == Decimal('10.0')

    def test_soil_temperature_fahrenheit_celsius_conversion(self):
        entry = self.monitor.create_entry(entry_models.SoilTemperature, timestamp=self.monitor.created, value=Decimal('68.0'))
        assert entry.fahrenheit == Decimal('68.0')
        assert entry.celsius == Decimal('20.0')

    def test_plain_value_entry_types_store_and_serialize(self):
        cases = [
            (entry_models.WindSpeed, Decimal('12.3')),
            (entry_models.WindDirection, Decimal('270.0')),
            (entry_models.Precipitation, Decimal('0.05')),
            (entry_models.SolarRadiation, Decimal('450.2')),
            (entry_models.NetRadiation, Decimal('-15.3')),
            (entry_models.VaporPressure, Decimal('1.25')),
            (entry_models.ETo, Decimal('0.012')),
            (entry_models.ETr, Decimal('0.015')),
        ]
        for EntryModel, value in cases:
            entry = self.monitor.create_entry(EntryModel, timestamp=self.monitor.created, value=value)
            assert entry.value == value
            assert entry.declared_data()['value'] == value
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `docker compose run --rm test pytest camp/apps/entries/tests/test_meteorological_entries.py -v`
Expected: FAIL with `AttributeError` / `ImportError` — `DewPoint` etc. don't exist yet.

- [ ] **Step 4: Add the 10 new entry classes to `meteorological.py`**

Append to `camp/apps/entries/models/meteorological.py` (after the existing `Pressure` class):

```python
class DewPoint(BaseEntry):
    label = _('Dew Point')
    units = '°F'

    value = models.DecimalField(
        max_digits=4, decimal_places=1,
        help_text=_('Dew point (°F)')
    )

    @property
    def fahrenheit(self):
        return self.value

    @fahrenheit.setter
    def fahrenheit(self, value):
        self.value = value

    @property
    def celsius(self):
        value = (Decimal(self.fahrenheit) - 32) * (Decimal(5) / Decimal(9))
        return value.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)

    @celsius.setter
    def celsius(self, value):
        value = (Decimal(value) * (Decimal(9) / Decimal(5))) + 32
        self.fahrenheit = value.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)

    def serialized_data(self):
        return {
            'dew_point_f': self.fahrenheit,
            'dew_point_c': self.celsius,
        }


class SoilTemperature(BaseEntry):
    label = _('Soil Temperature')
    units = '°F'

    value = models.DecimalField(
        max_digits=4, decimal_places=1,
        help_text=_('Soil temperature (°F)')
    )

    @property
    def fahrenheit(self):
        return self.value

    @fahrenheit.setter
    def fahrenheit(self, value):
        self.value = value

    @property
    def celsius(self):
        value = (Decimal(self.fahrenheit) - 32) * (Decimal(5) / Decimal(9))
        return value.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)

    @celsius.setter
    def celsius(self, value):
        value = (Decimal(value) * (Decimal(9) / Decimal(5))) + 32
        self.fahrenheit = value.quantize(Decimal('0.1'), rounding=ROUND_HALF_UP)

    def serialized_data(self):
        return {
            'soil_temperature_f': self.fahrenheit,
            'soil_temperature_c': self.celsius,
        }


class WindSpeed(BaseEntry):
    label = _('Wind Speed')
    units = 'mph'

    value = models.DecimalField(
        max_digits=5, decimal_places=1,
        help_text=_('Wind speed (mph)')
    )


class WindDirection(BaseEntry):
    label = _('Wind Direction')
    units = '°'

    value = models.DecimalField(
        max_digits=4, decimal_places=1,
        help_text=_('Wind direction (degrees)')
    )


class Precipitation(BaseEntry):
    label = _('Precipitation')
    units = 'in'

    value = models.DecimalField(
        max_digits=5, decimal_places=2,
        help_text=_('Precipitation (in)')
    )


class SolarRadiation(BaseEntry):
    label = _('Solar Radiation')
    units = 'W/m²'

    value = models.DecimalField(
        max_digits=6, decimal_places=1,
        help_text=_('Solar radiation (W/m²)')
    )


class NetRadiation(BaseEntry):
    label = _('Net Radiation')
    units = 'W/m²'

    value = models.DecimalField(
        max_digits=6, decimal_places=1,
        help_text=_('Net radiation (W/m²)')
    )


class VaporPressure(BaseEntry):
    label = _('Vapor Pressure')
    units = 'kPa'

    value = models.DecimalField(
        max_digits=4, decimal_places=2,
        help_text=_('Vapor pressure (kPa)')
    )


class ETo(BaseEntry):
    label = _('Reference Evapotranspiration')
    units = 'in'

    value = models.DecimalField(
        max_digits=5, decimal_places=3,
        help_text=_('ASCE reference evapotranspiration (in)')
    )


class ETr(BaseEntry):
    label = _('Alfalfa Reference Evapotranspiration')
    units = 'in'

    value = models.DecimalField(
        max_digits=5, decimal_places=3,
        help_text=_('ASCE alfalfa-reference evapotranspiration (in)')
    )
```

- [ ] **Step 5: Update `__init__.py` to re-export the new classes**

In `camp/apps/entries/models/__init__.py`, change:

```python
from .meteorological import Temperature, Humidity, Pressure
```

to:

```python
from .meteorological import (
    Temperature, Humidity, Pressure, DewPoint, SoilTemperature,
    WindSpeed, WindDirection, Precipitation, SolarRadiation,
    NetRadiation, VaporPressure, ETo, ETr,
)
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `docker compose run --rm test pytest camp/apps/entries/tests/test_meteorological_entries.py -v`
Expected: All PASS.

- [ ] **Step 7: Generate the migration**

Run: `docker compose run --rm web python manage.py makemigrations entries`
Expected: A new migration file created in `camp/apps/entries/migrations/` listing the 10 new models. Note the actual generated filename for the next step.

- [ ] **Step 8: Run the full test suite**

Run: `docker compose run --rm test pytest -v`
Expected: All PASS.

- [ ] **Step 9: Commit**

```bash
git add camp/apps/entries/models/meteorological.py camp/apps/entries/models/__init__.py camp/apps/entries/migrations/ camp/apps/entries/tests/test_meteorological_entries.py
git commit -m "feat: add generic meteorological entry types for CIMIS weather data"
```

---

### Task 4: Create the `CIMIS` monitor app skeleton

**Files:**
- Create: `camp/apps/monitors/cimis/__init__.py`
- Create: `camp/apps/monitors/cimis/apps.py`
- Create: `camp/apps/monitors/cimis/models.py`
- Create: `camp/apps/monitors/cimis/admin.py`
- Create: `camp/apps/monitors/cimis/tests.py`
- Modify: `camp/settings/base.py`
- Create: `camp/apps/monitors/cimis/migrations/0001_initial.py` (generated)

**Interfaces:**
- Consumes: `camp.apps.entries.models.{Temperature,Humidity,DewPoint,SoilTemperature,WindSpeed,WindDirection,Precipitation,SolarRadiation,NetRadiation,VaporPressure,ETo,ETr}` (Task 3), `camp.apps.monitors.models.Monitor`.
- Produces: `camp.apps.monitors.cimis.models.CIMIS` — a `Monitor` subclass with `station_number` field, `ENTRY_CONFIG`, and `ENTRY_MAP` (a `dict[str, EntryModel]` keyed by the CIMIS JSON field name, e.g. `'HlyAirTmp'`, built from `ENTRY_CONFIG`). Consumed by Task 6 and Task 7.

- [ ] **Step 1: Create the app package files**

Create `camp/apps/monitors/cimis/__init__.py` (empty file).

Create `camp/apps/monitors/cimis/apps.py`:

```python
from django.apps import AppConfig


class CimisConfig(AppConfig):
    name = 'camp.apps.monitors.cimis'
```

- [ ] **Step 2: Write the `CIMIS` model**

Create `camp/apps/monitors/cimis/models.py`:

```python
from django.contrib.gis.db import models

from camp.apps.entries import models as entry_models
from camp.apps.monitors.models import Monitor


class CIMIS(Monitor):
    LAST_ACTIVE_LIMIT = int(60 * 60 * 3)

    DATA_PROVIDERS = [{
        'name': 'California Department of Water Resources',
        'url': 'https://water.ca.gov',
    }]
    DATA_SOURCE = {
        'name': 'CIMIS',
        'url': 'https://cimis.water.ca.gov/',
    }
    DEVICE = 'CIMIS Weather Station'

    EXPECTED_INTERVAL = '1h'
    ENTRY_CONFIG = {
        entry_models.Temperature: {
            'fields': {'value': 'HlyAirTmp'},
            'allowed_stages': [entry_models.Temperature.Stage.RAW],
            'default_stage': entry_models.Temperature.Stage.RAW,
        },
        entry_models.Humidity: {
            'fields': {'value': 'HlyRelHum'},
            'allowed_stages': [entry_models.Humidity.Stage.RAW],
            'default_stage': entry_models.Humidity.Stage.RAW,
        },
        entry_models.DewPoint: {
            'fields': {'value': 'HlyDewPnt'},
            'allowed_stages': [entry_models.DewPoint.Stage.RAW],
            'default_stage': entry_models.DewPoint.Stage.RAW,
        },
        entry_models.SoilTemperature: {
            'fields': {'value': 'HlySoilTmp'},
            'allowed_stages': [entry_models.SoilTemperature.Stage.RAW],
            'default_stage': entry_models.SoilTemperature.Stage.RAW,
        },
        entry_models.WindSpeed: {
            'fields': {'value': 'HlyWindSpd'},
            'allowed_stages': [entry_models.WindSpeed.Stage.RAW],
            'default_stage': entry_models.WindSpeed.Stage.RAW,
        },
        entry_models.WindDirection: {
            'fields': {'value': 'HlyWindDir'},
            'allowed_stages': [entry_models.WindDirection.Stage.RAW],
            'default_stage': entry_models.WindDirection.Stage.RAW,
        },
        entry_models.Precipitation: {
            'fields': {'value': 'HlyPrecip'},
            'allowed_stages': [entry_models.Precipitation.Stage.RAW],
            'default_stage': entry_models.Precipitation.Stage.RAW,
        },
        entry_models.SolarRadiation: {
            'fields': {'value': 'HlySolRad'},
            'allowed_stages': [entry_models.SolarRadiation.Stage.RAW],
            'default_stage': entry_models.SolarRadiation.Stage.RAW,
        },
        entry_models.NetRadiation: {
            'fields': {'value': 'HlyNetRad'},
            'allowed_stages': [entry_models.NetRadiation.Stage.RAW],
            'default_stage': entry_models.NetRadiation.Stage.RAW,
        },
        entry_models.VaporPressure: {
            'fields': {'value': 'HlyVapPres'},
            'allowed_stages': [entry_models.VaporPressure.Stage.RAW],
            'default_stage': entry_models.VaporPressure.Stage.RAW,
        },
        entry_models.ETo: {
            'fields': {'value': 'HlyAsceEto'},
            'allowed_stages': [entry_models.ETo.Stage.RAW],
            'default_stage': entry_models.ETo.Stage.RAW,
        },
        entry_models.ETr: {
            'fields': {'value': 'HlyAsceEtr'},
            'allowed_stages': [entry_models.ETr.Stage.RAW],
            'default_stage': entry_models.ETr.Stage.RAW,
        },
    }

    GRADE = None

    station_number = models.CharField(max_length=20, unique=True)

    class Meta:
        verbose_name = 'CIMIS'

    ENTRY_MAP = {
        config['fields']['value']: EntryModel
        for EntryModel, config in ENTRY_CONFIG.items()
    }
```

Note: `ENTRY_MAP` is built as a class-body dict comprehension referencing `ENTRY_CONFIG` directly (not `cls.ENTRY_CONFIG`), matching the exact pattern already used in `camp/apps/monitors/airnow/models.py`.

- [ ] **Step 3: Write a minimal admin registration**

Create `camp/apps/monitors/cimis/admin.py`:

```python
from django.contrib.gis import admin

from camp.apps.monitors.admin import MonitorAdmin
from camp.apps.monitors.cimis.models import CIMIS


@admin.register(CIMIS)
class CIMISAdmin(MonitorAdmin):
    list_display = MonitorAdmin.list_display[:]
    list_display.remove('get_health_grade')

    fields = MonitorAdmin.fields
    readonly_fields = ['name', 'location', 'position', 'county', 'station_number', 'get_map']

    def has_add_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
```

- [ ] **Step 4: Register the app and add the settings entry**

In `camp/settings/base.py`, find the `INSTALLED_APPS` block containing:

```python
    'camp.apps.monitors.airgradient',
    'camp.apps.monitors.airnow',
    'camp.apps.monitors.aqview',
    'camp.apps.monitors.bam',
    'camp.apps.monitors.purpleair',
```

Change it to:

```python
    'camp.apps.monitors.airgradient',
    'camp.apps.monitors.airnow',
    'camp.apps.monitors.aqview',
    'camp.apps.monitors.bam',
    'camp.apps.monitors.cimis',
    'camp.apps.monitors.purpleair',
```

Add the API key setting near the other provider keys (after the `AIRNOW_API_KEY` block):

```python
# CIMIS

CIMIS_APP_KEY = env('CIMIS_APP_KEY')
```

- [ ] **Step 5: Write a placeholder test to confirm the model is registered correctly**

Create `camp/apps/monitors/cimis/tests.py`:

```python
from django.contrib.gis.geos import Point
from django.test import TestCase

from camp.apps.entries import models as entry_models
from camp.apps.monitors.cimis.models import CIMIS


class CIMISModelTests(TestCase):
    def test_entry_config_maps_all_twelve_fields(self):
        assert len(CIMIS.ENTRY_CONFIG) == 12
        assert CIMIS.ENTRY_MAP['HlyAirTmp'] is entry_models.Temperature
        assert CIMIS.ENTRY_MAP['HlyAsceEto'] is entry_models.ETo

    def test_station_number_is_unique(self):
        CIMIS.objects.create(
            name='Station A',
            station_number='2',
            position=Point(-119.7871, 36.7378, srid=4326),
            location=CIMIS.LOCATION.outside,
        )
        with self.assertRaises(Exception):
            CIMIS.objects.create(
                name='Station B',
                station_number='2',
                position=Point(-119.0, 36.0, srid=4326),
                location=CIMIS.LOCATION.outside,
            )

    def test_supports_health_checks_is_false(self):
        monitor = CIMIS.objects.create(
            name='Station A',
            station_number='2',
            position=Point(-119.7871, 36.7378, srid=4326),
            location=CIMIS.LOCATION.outside,
        )
        assert monitor.supports_health_checks() is False
```

- [ ] **Step 6: Generate the initial migration**

Run: `docker compose run --rm web python manage.py makemigrations cimis`
Expected: `camp/apps/monitors/cimis/migrations/0001_initial.py` created.

- [ ] **Step 7: Run migrations and the new tests**

Run: `docker compose run --rm web python manage.py migrate`
Expected: `Applying cimis.0001_initial... OK`.

Run: `docker compose run --rm test pytest camp/apps/monitors/cimis/tests.py -v`
Expected: All PASS. (`test_station_number_is_unique` will fail loudly if the migration didn't apply the `unique=True` constraint — if it does, re-check Step 6's generated migration before proceeding.)

- [ ] **Step 8: Commit**

```bash
git add camp/apps/monitors/cimis camp/settings/base.py
git commit -m "feat: add CIMIS monitor model and app registration"
```

---

### Task 5: `CIMISAPI` client

Hits the real, documented CIMIS REST API directly (`https://et.water.ca.gov/api/`) — confirmed via CIMIS's own API docs, not the third-party `python-CIMIS` package. Two endpoints: `GET /api/station` (all stations) and `GET /api/data` (hourly/daily readings by station, date range, and data item codes).

**Files:**
- Create: `camp/apps/monitors/cimis/api.py`
- Test: `camp/apps/monitors/cimis/tests.py` (append)

**Interfaces:**
- Consumes: `settings.CIMIS_APP_KEY` (Task 4).
- Produces: `camp.apps.monitors.cimis.api.CIMISAPI` with methods `get_stations() -> list[dict]` and `get_hourly_data(station_numbers: list[str], start_date: date, end_date: date, data_items: list[str]) -> list[dict]` (list of "Provider" dicts, each with a `'Records'` key). Consumed by Task 6 and Task 7.

- [ ] **Step 1: Write the failing tests**

Append to `camp/apps/monitors/cimis/tests.py`:

```python
from unittest.mock import MagicMock, patch

from camp.apps.monitors.cimis.api import CIMISAPI


def make_response(status_code=200, json_result=None):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_result
    response.raise_for_status = MagicMock()
    if status_code >= 400:
        response.raise_for_status.side_effect = Exception(f'HTTP {status_code}')
    return response


class CIMISAPITests(TestCase):
    def setUp(self):
        self.api = CIMISAPI(app_key='test-key')

    @patch('camp.apps.monitors.cimis.api.requests.Session.get')
    def test_get_stations_returns_station_list(self, mock_get):
        mock_get.return_value = make_response(json_result={'Stations': [{'StationNbr': '2'}]})

        stations = self.api.get_stations()

        assert stations == [{'StationNbr': '2'}]
        called_url, called_kwargs = mock_get.call_args
        assert called_url[0] == 'https://et.water.ca.gov/api/station'
        assert called_kwargs['params']['appKey'] == 'test-key'

    @patch('camp.apps.monitors.cimis.api.requests.Session.get')
    def test_get_hourly_data_builds_correct_params(self, mock_get):
        mock_get.return_value = make_response(json_result={
            'Data': {'Providers': [{'Name': 'cimis', 'Records': []}]}
        })

        from datetime import date
        providers = self.api.get_hourly_data(
            station_numbers=['2', '5'],
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 1),
            data_items=['hly-air-tmp', 'hly-wind-spd'],
        )

        assert providers == [{'Name': 'cimis', 'Records': []}]
        called_url, called_kwargs = mock_get.call_args
        assert called_url[0] == 'https://et.water.ca.gov/api/data'
        params = called_kwargs['params']
        assert params['targets'] == '2,5'
        assert params['startDate'] == '2026-07-01'
        assert params['endDate'] == '2026-07-01'
        assert params['dataItems'] == 'hly-air-tmp,hly-wind-spd'
        assert params['unitOfMeasure'] == 'E'
        assert params['appKey'] == 'test-key'
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `docker compose run --rm test pytest camp/apps/monitors/cimis/tests.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'camp.apps.monitors.cimis.api'`.

- [ ] **Step 3: Write the client**

Create `camp/apps/monitors/cimis/api.py`:

```python
import requests

from django.conf import settings


class CIMISAPI:
    base_url = 'https://et.water.ca.gov/api'

    def __init__(self, app_key=None):
        self.app_key = app_key or settings.CIMIS_APP_KEY
        self.session = requests.Session()

    def get_stations(self):
        response = self.session.get(f'{self.base_url}/station', params={
            'appKey': self.app_key,
        })
        response.raise_for_status()
        return response.json()['Stations']

    def get_hourly_data(self, station_numbers, start_date, end_date, data_items):
        params = {
            'appKey': self.app_key,
            'targets': ','.join(str(n) for n in station_numbers),
            'startDate': start_date.strftime('%Y-%m-%d'),
            'endDate': end_date.strftime('%Y-%m-%d'),
            'dataItems': ','.join(data_items),
            'unitOfMeasure': 'E',
        }
        response = self.session.get(f'{self.base_url}/data', params=params)
        response.raise_for_status()
        return response.json()['Data']['Providers']
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `docker compose run --rm test pytest camp/apps/monitors/cimis/tests.py -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add camp/apps/monitors/cimis/api.py camp/apps/monitors/cimis/tests.py
git commit -m "feat: add CIMISAPI client for the CIMIS REST API"
```

---

### Task 6: Station discovery task

Periodically fetches all CIMIS stations, filters to San Joaquin Valley counties (matching the `County.names` filter `AQview`'s discovery task uses), and `get_or_create`s a `CIMIS` monitor per `station_number`. CIMIS reports coordinates in HMS format with a decimal value after a `/` (e.g. `"36º20'10N / 36.3360"`) — confirmed against CIMIS's own API docs, matching the parsing approach used by the (otherwise not depended-on) `python-CIMIS` library.

**Files:**
- Create: `camp/apps/monitors/cimis/tasks.py`
- Test: `camp/apps/monitors/cimis/tests.py` (append)

**Interfaces:**
- Consumes: `camp.apps.monitors.cimis.api.CIMISAPI.get_stations()` (Task 5), `camp.apps.monitors.cimis.models.CIMIS` (Task 4), `camp.utils.counties.County.names`.
- Produces: `discover_cimis_stations` (Huey periodic task), `process_cimis_station(station: dict) -> CIMIS | Literal[False]`, `parse_hms_coordinate(value: str) -> float | None` — the latter two consumed by tests directly and, for `process_cimis_station`, called by `discover_cimis_stations`.

- [ ] **Step 1: Write the failing tests**

Append to `camp/apps/monitors/cimis/tests.py`:

```python
from camp.apps.monitors.cimis.tasks import parse_hms_coordinate, process_cimis_station


class ParseHmsCoordinateTests(TestCase):
    def test_parses_valid_latitude(self):
        assert parse_hms_coordinate("36º20'10N / 36.3360") == 36.3360

    def test_parses_valid_negative_longitude(self):
        assert parse_hms_coordinate("-120º6'47W / -120.1130") == -120.1130

    def test_returns_none_for_missing_slash(self):
        assert parse_hms_coordinate('garbage') is None

    def test_returns_none_for_empty_string(self):
        assert parse_hms_coordinate('') is None


class ProcessCimisStationTests(TestCase):
    def make_station(self, **overrides):
        station = {
            'StationNbr': '2',
            'Name': 'Five Points',
            'County': 'Fresno',
            'IsActive': 'True',
            'HmsLatitude': "36º20'10N / 36.3360",
            'HmsLongitude': "-120º6'47W / -120.1130",
        }
        station.update(overrides)
        return station

    def test_creates_monitor_for_active_sjv_county_station(self):
        monitor = process_cimis_station(self.make_station())

        assert monitor is not False
        assert monitor.station_number == '2'
        assert monitor.county == 'Fresno'

    def test_skips_station_outside_sjv_counties(self):
        result = process_cimis_station(self.make_station(County='Los Angeles'))
        assert result is False

    def test_skips_inactive_station(self):
        result = process_cimis_station(self.make_station(IsActive='False'))
        assert result is False

    def test_skips_station_with_unparseable_coordinates(self):
        result = process_cimis_station(self.make_station(HmsLatitude='garbage'))
        assert result is False

    def test_is_idempotent_for_existing_station(self):
        process_cimis_station(self.make_station())
        result = process_cimis_station(self.make_station(Name='Five Points Updated'))

        from camp.apps.monitors.cimis.models import CIMIS
        assert CIMIS.objects.filter(station_number='2').count() == 1
        assert result is not False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `docker compose run --rm test pytest camp/apps/monitors/cimis/tests.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'camp.apps.monitors.cimis.tasks'`.

- [ ] **Step 3: Write the task module**

Create `camp/apps/monitors/cimis/tasks.py`:

```python
from django.contrib.gis.geos import Point

from django_huey import db_task, db_periodic_task
from huey import crontab

from camp.apps.monitors.cimis.api import CIMISAPI
from camp.apps.monitors.cimis.models import CIMIS
from camp.utils.counties import County


def parse_hms_coordinate(value):
    if not value or '/' not in value:
        return None
    try:
        return float(value.split('/')[1].strip())
    except (ValueError, IndexError):
        return None


@db_periodic_task(crontab(hour='3', minute='0'), priority=50)
def discover_cimis_stations():
    api = CIMISAPI()
    for station in api.get_stations():
        process_cimis_station.call_local(station)


@db_task(priority=50)
def process_cimis_station(station):
    county = station.get('County')
    if county not in County.names:
        return False

    if station.get('IsActive') != 'True':
        return False

    latitude = parse_hms_coordinate(station.get('HmsLatitude'))
    longitude = parse_hms_coordinate(station.get('HmsLongitude'))
    if latitude is None or longitude is None:
        return False

    monitor, _created = CIMIS.objects.get_or_create(
        station_number=station['StationNbr'],
        defaults={
            'name': f"CIMIS #{station['StationNbr']} - {station.get('Name', '')}",
            'position': Point(longitude, latitude, srid=4326),
            'location': CIMIS.LOCATION.outside,
        },
    )
    return monitor
```

Note: `.call_local(station)` runs a `db_task`-decorated function synchronously in-process rather than enqueueing it — matching the exact pattern `AQview`'s `import_aqview_data` uses to call `process_aqview_data.call_local(row)`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `docker compose run --rm test pytest camp/apps/monitors/cimis/tests.py -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add camp/apps/monitors/cimis/tasks.py camp/apps/monitors/cimis/tests.py
git commit -m "feat: add CIMIS station discovery task"
```

---

### Task 7: Hourly data ingestion

Pulls the latest hourly data for all known `CIMIS` monitors and creates entries for each of the 12 mapped fields. CIMIS's per-field `Qc` flag marks data quality (`' '` = acceptable, `'R'`/`'H'`/`'S'` = estimated/suspect-high/suspect-low, `'N'` = not available) — we skip a field if it's not present in the record, has no `Value`, or is flagged `'N'`; we still ingest `R`/`H`/`S`-flagged values since they're still real numeric readings useful for weather context (unlike PM2.5, this data isn't used for regulatory determinations). CIMIS's `Hour` field runs `0100`-`2400` (not `0000`-`2300`), so `'2400'` needs special-casing to roll over to midnight of the next day.

**Files:**
- Modify: `camp/apps/monitors/cimis/models.py`
- Modify: `camp/apps/monitors/cimis/tasks.py`
- Test: `camp/apps/monitors/cimis/tests.py` (append)

**Interfaces:**
- Consumes: `camp.apps.monitors.cimis.api.CIMISAPI.get_hourly_data()` (Task 5), `Monitor.create_entry()` (existing, `camp/apps/monitors/models.py:374`).
- Produces: `CIMIS.parse_timestamp(record: dict) -> datetime`, `CIMIS.handle_payload(record: dict) -> list[BaseEntry]` on the model; `import_cimis_data` (Huey periodic task) and `process_cimis_data(record: dict) -> list[BaseEntry] | Literal[False]` in `tasks.py`.

- [ ] **Step 1: Write the failing tests for `CIMIS.parse_timestamp` and `CIMIS.handle_payload`**

Append to `camp/apps/monitors/cimis/tests.py`:

```python
from datetime import datetime


class CimisParseTimestampTests(TestCase):
    def setUp(self):
        self.monitor = CIMIS.objects.create(
            name='Station A',
            station_number='2',
            position=Point(-119.7871, 36.7378, srid=4326),
            location=CIMIS.LOCATION.outside,
        )

    def test_parses_normal_hour(self):
        timestamp = self.monitor.parse_timestamp({'Date': '2026-07-01', 'Hour': '0100'})
        local = timestamp.astimezone(timestamp.tzinfo)
        assert (local.year, local.month, local.day, local.hour, local.minute) == (2026, 7, 1, 1, 0)

    def test_parses_midnight_boundary_hour_2400(self):
        timestamp = self.monitor.parse_timestamp({'Date': '2026-07-01', 'Hour': '2400'})
        local = timestamp.astimezone(timestamp.tzinfo)
        assert (local.year, local.month, local.day, local.hour, local.minute) == (2026, 7, 2, 0, 0)


class CimisHandlePayloadTests(TestCase):
    def setUp(self):
        self.monitor = CIMIS.objects.create(
            name='Station A',
            station_number='2',
            position=Point(-119.7871, 36.7378, srid=4326),
            location=CIMIS.LOCATION.outside,
        )

    def make_record(self, **overrides):
        record = {
            'Date': '2026-07-01',
            'Hour': '1300',
            'Station': '2',
            'HlyAirTmp': {'Value': '95.4', 'Qc': ' ', 'Unit': '(F)'},
            'HlyRelHum': {'Value': '22.0', 'Qc': ' ', 'Unit': '(%)'},
            'HlyWindSpd': {'Value': '5.1', 'Qc': 'R', 'Unit': '(mph)'},
            'HlyAsceEto': {'Value': None, 'Qc': 'N', 'Unit': '(in)'},
        }
        record.update(overrides)
        return record

    def test_creates_entries_for_present_qc_acceptable_fields(self):
        entries = self.monitor.handle_payload(self.make_record())
        entry_types = {type(e) for e in entries}

        from camp.apps.entries import models as entry_models
        assert entry_models.Temperature in entry_types
        assert entry_models.Humidity in entry_types

    def test_ingests_estimated_qc_flagged_values(self):
        entries = self.monitor.handle_payload(self.make_record())

        from decimal import Decimal
        from camp.apps.entries import models as entry_models
        wind_entries = [e for e in entries if isinstance(e, entry_models.WindSpeed)]
        assert len(wind_entries) == 1
        assert wind_entries[0].value == Decimal('5.1')

    def test_skips_field_flagged_not_available(self):
        entries = self.monitor.handle_payload(self.make_record())

        from camp.apps.entries import models as entry_models
        assert not any(isinstance(e, entry_models.ETo) for e in entries)

    def test_skips_field_missing_from_record(self):
        record = self.make_record()
        del record['HlyRelHum']
        entries = self.monitor.handle_payload(record)

        from camp.apps.entries import models as entry_models
        assert not any(isinstance(e, entry_models.Humidity) for e in entries)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `docker compose run --rm test pytest camp/apps/monitors/cimis/tests.py -v`
Expected: FAIL with `AttributeError: 'CIMIS' object has no attribute 'parse_timestamp'`.

- [ ] **Step 3: Add `parse_timestamp` and `handle_payload` to the model**

In `camp/apps/monitors/cimis/models.py`, add these imports at the top:

```python
from datetime import datetime, timedelta

from django.conf import settings
```

Add these two methods to the `CIMIS` class (after `ENTRY_MAP`):

```python
    def parse_timestamp(self, record):
        date_str = record['Date']
        hour_str = record['Hour'].zfill(4)

        if hour_str == '2400':
            base = datetime.strptime(date_str, '%Y-%m-%d') + timedelta(days=1)
            naive = base.replace(hour=0, minute=0)
        else:
            naive = datetime.strptime(f'{date_str} {hour_str}', '%Y-%m-%d %H%M')

        return naive.replace(tzinfo=settings.DEFAULT_TIMEZONE)

    def handle_payload(self, record):
        timestamp = self.parse_timestamp(record)
        entries = []

        for field_name, EntryModel in self.ENTRY_MAP.items():
            item = record.get(field_name)
            if not item:
                continue

            if item.get('Qc') == 'N':
                continue

            value = item.get('Value')
            if value in (None, ''):
                continue

            entry = self.create_entry(EntryModel, timestamp=timestamp, value=value)
            if entry:
                entries.append(entry)

        return entries
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `docker compose run --rm test pytest camp/apps/monitors/cimis/tests.py -v`
Expected: All PASS.

- [ ] **Step 5: Write the failing tests for the ingestion task**

Append to `camp/apps/monitors/cimis/tests.py`:

```python
class ProcessCimisDataTests(TestCase):
    def setUp(self):
        self.monitor = CIMIS.objects.create(
            name='Station A',
            station_number='2',
            position=Point(-119.7871, 36.7378, srid=4326),
            location=CIMIS.LOCATION.outside,
        )

    def test_creates_entries_for_known_station(self):
        from camp.apps.monitors.cimis.tasks import process_cimis_data

        record = {
            'Date': '2026-07-01',
            'Hour': '1300',
            'Station': '2',
            'HlyAirTmp': {'Value': '95.4', 'Qc': ' ', 'Unit': '(F)'},
        }
        entries = process_cimis_data(record)

        assert entries is not False
        assert len(entries) == 1

    def test_returns_false_for_unknown_station(self):
        from camp.apps.monitors.cimis.tasks import process_cimis_data

        record = {'Date': '2026-07-01', 'Hour': '1300', 'Station': '999'}
        result = process_cimis_data(record)

        assert result is False


class ImportCimisDataTests(TestCase):
    def test_no_op_when_no_monitors_exist(self):
        from camp.apps.monitors.cimis.tasks import import_cimis_data
        # Should not raise even with zero CIMIS monitors in the DB.
        import_cimis_data()

    @patch('camp.apps.monitors.cimis.tasks.CIMISAPI')
    def test_calls_api_with_all_known_station_numbers(self, MockAPI):
        CIMIS.objects.create(
            name='Station A',
            station_number='2',
            position=Point(-119.7871, 36.7378, srid=4326),
            location=CIMIS.LOCATION.outside,
        )
        CIMIS.objects.create(
            name='Station B',
            station_number='5',
            position=Point(-119.0, 36.0, srid=4326),
            location=CIMIS.LOCATION.outside,
        )
        mock_instance = MockAPI.return_value
        mock_instance.get_hourly_data.return_value = []

        from camp.apps.monitors.cimis.tasks import import_cimis_data
        import_cimis_data()

        called_kwargs = mock_instance.get_hourly_data.call_args.kwargs
        assert sorted(called_kwargs['station_numbers']) == ['2', '5']
```

- [ ] **Step 6: Run the tests to verify they fail**

Run: `docker compose run --rm test pytest camp/apps/monitors/cimis/tests.py -v`
Expected: FAIL — `process_cimis_data` and `import_cimis_data` don't exist yet.

- [ ] **Step 7: Add the ingestion task to `tasks.py`**

In `camp/apps/monitors/cimis/tasks.py`, add `timezone` to the Django import and append these two tasks at the end of the file:

```python
from django.utils import timezone
```

```python
@db_periodic_task(crontab(minute='45'), priority=50)
def import_cimis_data():
    station_numbers = list(CIMIS.objects.values_list('station_number', flat=True))
    if not station_numbers:
        return

    today = timezone.localtime(timezone.now()).date()
    api = CIMISAPI()
    providers = api.get_hourly_data(
        station_numbers=station_numbers,
        start_date=today,
        end_date=today,
        data_items=list(CIMIS.ENTRY_MAP.keys()),
    )

    for provider in providers:
        for record in provider.get('Records', []):
            process_cimis_data.call_local(record)


@db_task(priority=50)
def process_cimis_data(record):
    try:
        monitor = CIMIS.objects.get(station_number=record['Station'])
    except CIMIS.DoesNotExist:
        return False

    return monitor.handle_payload(record)
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `docker compose run --rm test pytest camp/apps/monitors/cimis/tests.py -v`
Expected: All PASS.

- [ ] **Step 9: Run the full test suite**

Run: `docker compose run --rm test pytest -v`
Expected: All PASS.

- [ ] **Step 10: Commit**

```bash
git add camp/apps/monitors/cimis/models.py camp/apps/monitors/cimis/tasks.py camp/apps/monitors/cimis/tests.py
git commit -m "feat: add CIMIS hourly data ingestion task"
```

---

## Post-plan manual steps (not automatable)

- Request a free CIMIS app key from CDWR and set `CIMIS_APP_KEY` in your local `.env` (not `.env.test` — tests mock the API client and never make real requests).
- Deploy config: add `CIMIS_APP_KEY` to the production environment's secrets.
