# VOZbox Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate VOZbox air quality monitors (deployed by CCEJN) into SJVAir by ingesting CSV data published to GitHub, running the full LCS calibration pipeline for PM2.5, and providing a backfill command for externally calibrated O3.

**Architecture:** A `VozBoxClient` context manager handles all GitHub HTTP I/O and CSV parsing, returning normalized row dicts. A `VOZBox` Django model (inheriting `Monitor` directly — not `LCSMixin`, because `coreid` is a hex string not an integer) stores monitors keyed by `coreid`. A periodic task polls today's and yesterday's daily CSVs every 10 minutes, auto-creating monitors and running the entry pipeline. An `import_vozbox_cal` management command backfills calibrated O3 from the `moospmV3_cal` folder. An `O3_VOZBox` processor stub in the calibrations app is inactive until a `DefaultCalibration` record is created.

**Tech Stack:** Django, `requests`, Python `csv`/`tempfile`, `django-huey`, existing `camp.apps.calibrations` processor infrastructure.

**Spec:** `docs/superpowers/specs/2026-06-12-vozbox-integration-design.md`

---

## File Map

**Create:**
- `camp/apps/monitors/vozbox/__init__.py`
- `camp/apps/monitors/vozbox/apps.py`
- `camp/apps/monitors/vozbox/admin.py`
- `camp/apps/monitors/vozbox/api.py` — `VozBoxClient`
- `camp/apps/monitors/vozbox/models.py` — `VOZBox` monitor
- `camp/apps/monitors/vozbox/tasks.py` — `import_realtime`, `process_device`
- `camp/apps/monitors/vozbox/management/__init__.py`
- `camp/apps/monitors/vozbox/management/commands/__init__.py`
- `camp/apps/monitors/vozbox/management/commands/import_vozbox_cal.py`
- `camp/apps/monitors/vozbox/migrations/__init__.py`
- `camp/apps/monitors/vozbox/migrations/0001_initial.py` (generated)
- `camp/apps/monitors/vozbox/tests.py`
- `camp/apps/calibrations/core/processors/o3.py` — `O3_VOZBox` processor

**Modify:**
- `camp/settings/base.py` — add `'camp.apps.monitors.vozbox'` to `INSTALLED_APPS`

---

## Task 1: Scaffold the module

**Files:**
- Create: `camp/apps/monitors/vozbox/__init__.py`
- Create: `camp/apps/monitors/vozbox/apps.py`
- Create: `camp/apps/monitors/vozbox/migrations/__init__.py`
- Create: `camp/apps/monitors/vozbox/management/__init__.py`
- Create: `camp/apps/monitors/vozbox/management/commands/__init__.py`
- Modify: `camp/settings/base.py`

- [ ] **Step 1: Create the directory structure**

```bash
mkdir -p camp/apps/monitors/vozbox/migrations
mkdir -p camp/apps/monitors/vozbox/management/commands
touch camp/apps/monitors/vozbox/__init__.py
touch camp/apps/monitors/vozbox/migrations/__init__.py
touch camp/apps/monitors/vozbox/management/__init__.py
touch camp/apps/monitors/vozbox/management/commands/__init__.py
```

- [ ] **Step 2: Write apps.py**

`camp/apps/monitors/vozbox/apps.py`:
```python
from django.apps import AppConfig


class VozboxConfig(AppConfig):
    name = 'camp.apps.monitors.vozbox'
```

- [ ] **Step 3: Register in INSTALLED_APPS**

In `camp/settings/base.py`, add after `'camp.apps.monitors.purpleair'`:
```python
    'camp.apps.monitors.vozbox',
```

- [ ] **Step 4: Commit**

```bash
git add camp/apps/monitors/vozbox/ camp/settings/base.py
git commit -m "feat(vozbox): scaffold module structure"
```

---

## Task 2: VozBoxClient — CSV parsing

**Files:**
- Create: `camp/apps/monitors/vozbox/api.py`
- Create: `camp/apps/monitors/vozbox/tests.py`

This task covers the pure-Python CSV parsing logic. HTTP is tested separately in Task 3.

- [ ] **Step 1: Write failing tests for CSV parsing**

`camp/apps/monitors/vozbox/tests.py`:
```python
import csv
import io
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.test import TestCase

from camp.apps.monitors.vozbox.api import VozBoxClient


DAILY_CSV = """\
"","objectId","event","unixtime","m_PM1_CF1","m_PM1_ATM","m_PM1_b","m_PM25_CF1","m_PM25_ATM","m_PM25_b","m_PM4_b","m_PM10_CF1","m_PM10_ATM","m_PM10_b","n_PM03_P","n_PM05_P","n_PM05_b","n_PM1_P","n_PM1_b","n_PM25_P","n_PM25_b","n_PM4_b","tempC_pms","rh_pms","n_PM10_b","typ_size_b","temp_C","tempC_sen5x","rh","rh_sen5x","o3","vocIdx","noxIdx","lat","lon","alt","sats","counter","moos","ver","coreid","published_at","createdAt","updatedAt","date"
"1","abc","MOOSPMv3Parser",1749427200,7,7,4,10,10,4,4,10,10,4,1598,443,22378,54,30,2,30,30,34,20,30,0,36,39,26,25,70.0,74,1,36.785328,-119.773125,72.5,5,600,58,3,"e00fce68f12da1a0c5de6248",2025-06-09 00:00:02,2025-06-09 00:00:03,2025-06-09 00:00:03,2025-06-09
"2","def","MOOSPMv3Parser",1749427200,6,6,3,9,9,3,3,9,9,3,1573,396,25264,57,32,3,32,32,34,18,32,0,35,38,27,24,65.0,55,1,36.785351,-119.773140,74.9,7,600,58,3,"e00fce68e88237db75a60608",2025-06-09 00:00:02,2025-06-09 00:00:03,2025-06-09 00:00:03,2025-06-09
"""

CAL_CSV = """\
unixtime,m_PM25_CF1,m_PM25_ATM,m_PM25_b,m_PM10_CF1,m_PM10_ATM,m_PM10_b,temp_C,rh,o3,lat,lon,coreid,C1_T,C2_rh,C3_o3,b,o3_cal
1750428000,5,5,4,6,6,4,16,54,26.981,36.785343,-119.773056,e00fce682bbf742cd0b6768a,0.594,−0.117,0.426,8.44,23.127
1750428000,0,0,4,1,1,4,16,53,0.0,36.785404,-119.773109,e00fce68b74b750aa2a7da46,,,,,-999.0
"""


class VozBoxClientParseTests(TestCase):
    def _write_csv(self, content):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, encoding='utf-8') as f:
            f.write(content)
            return Path(f.name)

    def test_parse_daily_csv_groups_by_coreid(self):
        with VozBoxClient() as client:
            path = self._write_csv(DAILY_CSV)
            result = client.parse_csv(path)

        assert 'e00fce68f12da1a0c5de6248' in result
        assert 'e00fce68e88237db75a60608' in result
        assert len(result) == 2

    def test_parse_daily_csv_normalizes_row(self):
        with VozBoxClient() as client:
            path = self._write_csv(DAILY_CSV)
            result = client.parse_csv(path)

        row = result['e00fce68f12da1a0c5de6248'][0]
        assert row['timestamp'] == datetime(2025, 6, 9, 0, 0, 0, tzinfo=timezone.utc)
        assert row['pm1_a'] == 7.0
        assert row['pm1_b'] == 4.0
        assert row['pm25_a'] == 10.0
        assert row['pm25_b'] == 4.0
        assert row['pm10_a'] == 10.0
        assert row['pm10_b'] == 4.0
        assert row['temperature'] == 36.0
        assert row['humidity'] == 26.0
        assert row['o3'] == 70.0
        assert row['latitude'] == 36.785328
        assert row['longitude'] == -119.773125

    def test_parse_cal_csv_includes_o3_cal(self):
        with VozBoxClient() as client:
            path = self._write_csv(CAL_CSV)
            result = client.parse_csv(path)

        row = result['e00fce682bbf742cd0b6768a'][0]
        assert row['o3_cal'] == 23.127
        assert row['pm25_a'] == 5.0
        assert row['pm1_a'] is None   # cal CSV has no m_PM1_ATM column

    def test_parse_cal_csv_returns_none_o3_cal_for_invalid_row(self):
        with VozBoxClient() as client:
            path = self._write_csv(CAL_CSV)
            result = client.parse_csv(path)

        row = result['e00fce68b74b750aa2a7da46'][0]
        assert row['o3_cal'] == -999.0  # value exists but calibration invalid (handled by consumer)

    def test_parse_csv_skips_rows_without_coreid(self):
        content = (
            'unixtime,m_PM25_ATM,m_PM25_b,coreid\n'
            '1749427200,10,4,\n'
            '1749427200,10,4,e00fce68f12da1a0c5de6248\n'
        )
        with VozBoxClient() as client:
            path = self._write_csv(content)
            result = client.parse_csv(path)

        assert len(result) == 1

    def test_parse_csv_skips_rows_with_invalid_unixtime(self):
        content = (
            'unixtime,m_PM25_ATM,m_PM25_b,coreid\n'
            'notanumber,10,4,e00fce68f12da1a0c5de6248\n'
        )
        with VozBoxClient() as client:
            path = self._write_csv(content)
            result = client.parse_csv(path)

        assert result == {}
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker compose run --rm test pytest camp/apps/monitors/vozbox/tests.py -v
```
Expected: `ModuleNotFoundError` or `ImportError` — `VozBoxClient` doesn't exist yet.

- [ ] **Step 3: Implement VozBoxClient CSV parsing**

`camp/apps/monitors/vozbox/api.py`:
```python
import csv
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

import requests
from django.conf import settings


class VozBoxClient:
    OWNER = 'QuinnResearch'
    REPO = 'carbVoz_data'
    GITHUB_API = 'https://api.github.com'
    RAW_BASE = 'https://raw.githubusercontent.com'
    BRANCH = 'main'

    DAILY_FOLDER = 'moospmV3_daily'
    DAILY_PREFIX = 'moospmV3'
    CAL_FOLDER = 'moospmV3_cal'
    CAL_PREFIX = 'moospmV3_cal'

    def __init__(self):
        self._tmpdir = None
        self._session = None

    def __enter__(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        return self

    def __exit__(self, *args):
        if self._tmpdir:
            self._tmpdir.cleanup()
            self._tmpdir = None
        if self._session:
            self._session.close()
            self._session = None

    @property
    def session(self):
        if self._session is None:
            self._session = requests.Session()
            token = getattr(settings, 'GITHUB_API_TOKEN', None)
            if token:
                self._session.headers['Authorization'] = f'Bearer {token}'
        return self._session

    def _raw_url(self, folder, filename):
        return f'{self.RAW_BASE}/{self.OWNER}/{self.REPO}/{self.BRANCH}/{folder}/{filename}'

    def _api_url(self, path):
        return f'{self.GITHUB_API}/repos/{self.OWNER}/{self.REPO}/contents/{path}'

    def daily_filename(self, d: date) -> str:
        return f'{self.DAILY_PREFIX}_{d.strftime("%Y-%m-%d")}.csv'

    def cal_filename(self, d: date, hour_utc: int) -> str:
        return f'{self.CAL_PREFIX}_{d.strftime("%Y-%m-%d")}T{hour_utc}.csv'

    def download_csv(self, url: str) -> Optional[Path]:
        assert self._tmpdir is not None, 'VozBoxClient must be used as a context manager'
        response = self.session.get(url)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        filename = url.rsplit('/', 1)[-1]
        path = Path(self._tmpdir.name) / filename
        path.write_text(response.text, encoding='utf-8')
        return path

    def parse_csv(self, path: Path) -> dict:
        result = {}
        with path.open(encoding='utf-8') as fh:
            for raw_row in csv.DictReader(fh):
                coreid = raw_row.get('coreid', '').strip()
                if not coreid:
                    continue
                row = self._normalize_row(raw_row)
                if row is None:
                    continue
                result.setdefault(coreid, []).append(row)
        return result

    def _normalize_row(self, raw: dict) -> Optional[dict]:
        try:
            ts = datetime.fromtimestamp(int(raw['unixtime']), tz=timezone.utc)
        except (KeyError, ValueError, TypeError):
            return None

        def _float(key):
            val = raw.get(key, '').strip()
            try:
                return float(val)
            except (ValueError, TypeError):
                return None

        return {
            'timestamp': ts,
            'pm1_a': _float('m_PM1_ATM'),
            'pm1_b': _float('m_PM1_b'),
            'pm25_a': _float('m_PM25_ATM'),
            'pm25_b': _float('m_PM25_b'),
            'pm10_a': _float('m_PM10_ATM'),
            'pm10_b': _float('m_PM10_b'),
            'temperature': _float('temp_C'),
            'humidity': _float('rh'),
            'o3': _float('o3'),
            'o3_cal': _float('o3_cal'),
            'latitude': _float('lat'),
            'longitude': _float('lon'),
        }

    def get_daily_data(self, d: date) -> Optional[dict]:
        url = self._raw_url(self.DAILY_FOLDER, self.daily_filename(d))
        path = self.download_csv(url)
        if path is None:
            return None
        return self.parse_csv(path)

    def get_cal_data(self, d: date, hour_utc: int) -> Optional[dict]:
        url = self._raw_url(self.CAL_FOLDER, self.cal_filename(d, hour_utc))
        path = self.download_csv(url)
        if path is None:
            return None
        return self.parse_csv(path)

    def list_daily_files(self) -> list:
        url = self._api_url(self.DAILY_FOLDER)
        response = self.session.get(url)
        response.raise_for_status()
        results = []
        for item in response.json():
            name = item.get('name', '')
            if not (name.startswith(self.DAILY_PREFIX + '_') and name.endswith('.csv')):
                continue
            try:
                results.append(date.fromisoformat(name[len(self.DAILY_PREFIX) + 1:-4]))
            except ValueError:
                continue
        return sorted(results)

    def list_cal_files(self) -> list:
        url = self._api_url(self.CAL_FOLDER)
        response = self.session.get(url)
        response.raise_for_status()
        results = []
        for item in response.json():
            name = item.get('name', '')
            if not (name.startswith(self.CAL_PREFIX + '_') and name.endswith('.csv')):
                continue
            try:
                stem = name[len(self.CAL_PREFIX) + 1:-4]   # "2025-06-20T15"
                date_part, hour_part = stem.split('T')
                results.append((date.fromisoformat(date_part), int(hour_part)))
            except (ValueError, IndexError):
                continue
        return sorted(results)
```

- [ ] **Step 4: Run parsing tests to verify they pass**

```bash
docker compose run --rm test pytest camp/apps/monitors/vozbox/tests.py::VozBoxClientParseTests -v
```
Expected: All 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add camp/apps/monitors/vozbox/api.py camp/apps/monitors/vozbox/tests.py
git commit -m "feat(vozbox): add VozBoxClient CSV parsing"
```

---

## Task 3: VozBoxClient — HTTP methods

**Files:**
- Modify: `camp/apps/monitors/vozbox/tests.py` (add HTTP tests)

`api.py` is already complete from Task 2. This task adds tests for the HTTP-facing methods.

- [ ] **Step 1: Add HTTP tests to tests.py**

Append to `camp/apps/monitors/vozbox/tests.py`:
```python
class VozBoxClientHTTPTests(TestCase):
    def _make_response(self, status_code=200, text=''):
        resp = MagicMock()
        resp.status_code = status_code
        resp.text = text
        resp.json.return_value = []
        resp.raise_for_status = MagicMock()
        return resp

    @patch('camp.apps.monitors.vozbox.api.requests.Session')
    def test_get_daily_data_returns_none_on_404(self, MockSession):
        MockSession.return_value.__enter__ = lambda s: s
        MockSession.return_value.get.return_value = self._make_response(404)

        with VozBoxClient() as client:
            result = client.get_daily_data(date(2025, 6, 9))

        assert result is None

    @patch('camp.apps.monitors.vozbox.api.requests.Session')
    def test_get_daily_data_parses_csv_on_200(self, MockSession):
        MockSession.return_value.__enter__ = lambda s: s
        MockSession.return_value.get.return_value = self._make_response(200, text=DAILY_CSV)

        with VozBoxClient() as client:
            result = client.get_daily_data(date(2025, 6, 9))

        assert result is not None
        assert 'e00fce68f12da1a0c5de6248' in result

    @patch('camp.apps.monitors.vozbox.api.requests.Session')
    def test_list_daily_files_returns_sorted_dates(self, MockSession):
        api_response = MagicMock()
        api_response.status_code = 200
        api_response.raise_for_status = MagicMock()
        api_response.json.return_value = [
            {'name': 'moospmV3_2025-06-09.csv'},
            {'name': 'moospmV3_2025-06-08.csv'},
            {'name': '.RData'},
            {'name': 'carb_data_cleaning.Rout'},
        ]
        MockSession.return_value.__enter__ = lambda s: s
        MockSession.return_value.get.return_value = api_response

        with VozBoxClient() as client:
            result = client.list_daily_files()

        assert result == [date(2025, 6, 8), date(2025, 6, 9)]

    @patch('camp.apps.monitors.vozbox.api.requests.Session')
    def test_list_cal_files_returns_sorted_date_hour_tuples(self, MockSession):
        api_response = MagicMock()
        api_response.status_code = 200
        api_response.raise_for_status = MagicMock()
        api_response.json.return_value = [
            {'name': 'moospmV3_cal_2025-06-20T15.csv'},
            {'name': 'moospmV3_cal_2025-06-20T14.csv'},
        ]
        MockSession.return_value.__enter__ = lambda s: s
        MockSession.return_value.get.return_value = api_response

        with VozBoxClient() as client:
            result = client.list_cal_files()

        assert result == [(date(2025, 6, 20), 14), (date(2025, 6, 20), 15)]

    @patch('camp.apps.monitors.vozbox.api.requests.Session')
    def test_context_manager_cleans_up_tmpdir(self, MockSession):
        with VozBoxClient() as client:
            tmpdir_name = client._tmpdir.name
            assert Path(tmpdir_name).exists()
        assert not Path(tmpdir_name).exists()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker compose run --rm test pytest camp/apps/monitors/vozbox/tests.py::VozBoxClientHTTPTests -v
```
Expected: Failures because `requests.Session` is instantiated inside `session` property (not at `__init__`), so the mock path needs adjustment. See Step 3 for the fix.

The mock path `camp.apps.monitors.vozbox.api.requests.Session` is correct because the file imports `requests` at the top level. The `session` property creates `requests.Session()`. The test patches `requests.Session` before `session` is first accessed, so the mock works correctly. If you see import errors, check that `api.py` exists and imports `requests`.

- [ ] **Step 3: Run tests to verify they pass**

```bash
docker compose run --rm test pytest camp/apps/monitors/vozbox/tests.py::VozBoxClientHTTPTests -v
```
Expected: All 5 tests PASS.

- [ ] **Step 4: Run all client tests together**

```bash
docker compose run --rm test pytest camp/apps/monitors/vozbox/tests.py -v
```
Expected: All 10 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add camp/apps/monitors/vozbox/tests.py
git commit -m "feat(vozbox): add VozBoxClient HTTP tests"
```

---

## Task 4: VOZBox model

**Files:**
- Create: `camp/apps/monitors/vozbox/models.py`
- Create: `camp/apps/monitors/vozbox/migrations/0001_initial.py` (generated)
- Modify: `camp/apps/monitors/vozbox/tests.py`

**Note:** `VOZBox` inherits from `Monitor` directly — NOT from `LCSMixin`. `LCSMixin.sensor_id` is an `IntegerField`, but `coreid` is a 24-character hex string. We define our own `sensor_id = CharField`.

- [ ] **Step 1: Write failing model tests**

Append to `camp/apps/monitors/vozbox/tests.py`:
```python
from django.contrib.gis.geos import Point
from camp.apps.monitors.vozbox.models import VOZBox
from camp.apps.entries import models as entry_models


class VOZBoxModelTests(TestCase):
    def _make_row(self, **kwargs):
        defaults = {
            'timestamp': datetime(2025, 6, 9, 0, 0, 0, tzinfo=timezone.utc),
            'pm1_a': 7.0, 'pm1_b': 4.0,
            'pm25_a': 10.0, 'pm25_b': 4.0,
            'pm10_a': 10.0, 'pm10_b': 4.0,
            'temperature': 36.0,
            'humidity': 26.0,
            'o3': 70.0,
            'o3_cal': None,
            'latitude': 36.785328,
            'longitude': -119.773125,
        }
        defaults.update(kwargs)
        return defaults

    def test_update_data_sets_position(self):
        monitor = VOZBox(sensor_id='e00fce68f12da1a0c5de6248')
        monitor.update_data(self._make_row())
        assert monitor.position == Point(-119.773125, 36.785328)

    def test_update_data_sets_name_from_coreid_when_empty(self):
        monitor = VOZBox(sensor_id='e00fce68f12da1a0c5de6248')
        monitor.update_data(self._make_row())
        assert monitor.name == 'e00fce68f12da1a0c5de6248'

    def test_update_data_does_not_overwrite_existing_name(self):
        monitor = VOZBox(sensor_id='e00fce68f12da1a0c5de6248', name='Coalinga')
        monitor.update_data(self._make_row())
        assert monitor.name == 'Coalinga'

    def test_update_data_sets_location_outside(self):
        monitor = VOZBox(sensor_id='e00fce68f12da1a0c5de6248')
        monitor.update_data(self._make_row())
        assert monitor.location == 'outside'

    def test_supports_health_checks(self):
        monitor = VOZBox(sensor_id='e00fce68f12da1a0c5de6248')
        assert monitor.supports_health_checks() is True

    def test_create_entries_produces_all_types(self):
        monitor = VOZBox.objects.create(
            sensor_id='e00fce68f12da1a0c5de6248',
            name='Test',
            location='outside',
        )
        row = self._make_row()
        entries = monitor.create_entries(row)
        entry_types = {type(e) for e in entries}
        assert entry_models.PM10 in entry_types    # PM1.0
        assert entry_models.PM25 in entry_types
        assert entry_models.PM100 in entry_types
        assert entry_models.Temperature in entry_types
        assert entry_models.Humidity in entry_types
        assert entry_models.O3 in entry_types

    def test_create_entries_dual_channel_pm25(self):
        monitor = VOZBox.objects.create(
            sensor_id='e00fce68f12da1a0c5de6248',
            name='Test',
            location='outside',
        )
        row = self._make_row()
        entries = monitor.create_entries(row)
        pm25_entries = [e for e in entries if isinstance(e, entry_models.PM25)]
        sensors = {e.sensor for e in pm25_entries}
        assert sensors == {'a', 'b'}

    def test_create_entries_skips_none_values(self):
        monitor = VOZBox.objects.create(
            sensor_id='e00fce68f12da1a0c5de6248',
            name='Test',
            location='outside',
        )
        row = self._make_row(pm25_a=None)
        entries = monitor.create_entries(row)
        pm25_a_entries = [e for e in entries if isinstance(e, entry_models.PM25) and e.sensor == 'a']
        assert pm25_a_entries == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker compose run --rm test pytest camp/apps/monitors/vozbox/tests.py::VOZBoxModelTests -v
```
Expected: `ImportError` — `VOZBox` doesn't exist yet.

- [ ] **Step 3: Implement VOZBox model**

`camp/apps/monitors/vozbox/models.py`:
```python
from django.contrib.gis.db import models
from django.contrib.gis.geos import Point
from django.utils.translation import gettext_lazy as _

from camp.apps.calibrations import processors
from camp.apps.entries import models as entry_models
from camp.apps.monitors.models import Monitor


class VOZBox(Monitor):
    DATA_PROVIDERS = [{'name': 'CCEJN', 'url': 'https://ccejn.org/'}]
    DATA_SOURCE = {'name': 'VOZbox', 'url': 'https://ccejn.org/'}
    EXPECTED_INTERVAL = '10 min'
    GRADE = Monitor.Grade.LCS

    ENTRY_CONFIG = {
        entry_models.PM10: {
            'sensors': ['a', 'b'],
            'allowed_stages': [entry_models.PM10.Stage.RAW],
            'default_stage': entry_models.PM10.Stage.RAW,
        },
        entry_models.PM25: {
            'sensors': ['a', 'b'],
            'allowed_stages': [
                entry_models.PM25.Stage.RAW,
                entry_models.PM25.Stage.CORRECTED,
                entry_models.PM25.Stage.CLEANED,
                entry_models.PM25.Stage.CALIBRATED,
            ],
            'default_stage': entry_models.PM25.Stage.CLEANED,
            'processors': {
                entry_models.PM25.Stage.RAW: [processors.PM25_LCS_Correction],
                entry_models.PM25.Stage.CORRECTED: [processors.PM25_LCS_Cleaning],
                entry_models.PM25.Stage.CLEANED: [
                    processors.PM25_UnivariateLinearRegression,
                    processors.PM25_MultivariateLinearRegression,
                    processors.PM25_EPA_Oct2021,
                ],
            },
            'alerts': {
                'stage': entry_models.PM25.Stage.CALIBRATED,
                'processor': processors.PM25_UnivariateLinearRegression,
            },
        },
        entry_models.PM100: {
            'sensors': ['a', 'b'],
            'allowed_stages': [entry_models.PM100.Stage.RAW],
            'default_stage': entry_models.PM100.Stage.RAW,
        },
        entry_models.Temperature: {
            'sensors': ['1'],
            'allowed_stages': [entry_models.Temperature.Stage.RAW],
            'default_stage': entry_models.Temperature.Stage.RAW,
        },
        entry_models.Humidity: {
            'sensors': ['1'],
            'allowed_stages': [entry_models.Humidity.Stage.RAW],
            'default_stage': entry_models.Humidity.Stage.RAW,
        },
        entry_models.O3: {
            'sensors': ['1'],
            'allowed_stages': [
                entry_models.O3.Stage.RAW,
                entry_models.O3.Stage.CALIBRATED,
            ],
            'default_stage': entry_models.O3.Stage.RAW,
            'processors': {
                entry_models.O3.Stage.RAW: [processors.O3_VOZBox],
            },
        },
    }

    sensor_id = models.CharField(_('sensor ID'), max_length=64, unique=True)

    class Meta:
        verbose_name = 'VOZbox'

    def update_data(self, row):
        if not self.name:
            self.name = self.sensor_id
        if row.get('latitude') and row.get('longitude'):
            self.position = Point(float(row['longitude']), float(row['latitude']))
        self.location = self.LOCATION.outside

    def create_entries(self, row):
        timestamp = row['timestamp']
        entries = []

        dual_channel = {
            'a': {
                entry_models.PM10: {'value': row.get('pm1_a')},
                entry_models.PM25: {'value': row.get('pm25_a')},
                entry_models.PM100: {'value': row.get('pm10_a')},
            },
            'b': {
                entry_models.PM10: {'value': row.get('pm1_b')},
                entry_models.PM25: {'value': row.get('pm25_b')},
                entry_models.PM100: {'value': row.get('pm10_b')},
            },
        }
        single_channel = {
            entry_models.Temperature: {'celsius': row.get('temperature')},
            entry_models.Humidity: {'value': row.get('humidity')},
            entry_models.O3: {'value': row.get('o3')},
        }

        for sensor, model_map in dual_channel.items():
            for EntryModel, data in model_map.items():
                entry = self.create_entry(EntryModel, timestamp=timestamp, sensor=sensor, **data)
                if entry is not None:
                    entries.append(entry)

        for EntryModel, data in single_channel.items():
            entry = self.create_entry(EntryModel, timestamp=timestamp, sensor='1', **data)
            if entry is not None:
                entries.append(entry)

        return entries

    def create_entry(self, EntryModel, **data):
        if any(v is None for v in data.values()):
            return
        return super().create_entry(EntryModel, **data)
```

- [ ] **Step 4: Generate migration**

```bash
docker compose run --rm web python manage.py makemigrations vozbox
```
Expected output: `Migrations for 'vozbox': camp/apps/monitors/vozbox/migrations/0001_initial.py`

- [ ] **Step 5: Run migration**

```bash
docker compose run --rm web python manage.py migrate vozbox
```
Expected output: `Applying vozbox.0001_initial... OK`

- [ ] **Step 6: Run model tests**

```bash
docker compose run --rm test pytest camp/apps/monitors/vozbox/tests.py::VOZBoxModelTests -v
```
Expected: All 8 tests PASS.

- [ ] **Step 7: Commit**

```bash
git add camp/apps/monitors/vozbox/models.py camp/apps/monitors/vozbox/migrations/ camp/apps/monitors/vozbox/tests.py
git commit -m "feat(vozbox): add VOZBox monitor model and migration"
```

---

## Task 5: O3_VOZBox processor

**Files:**
- Create: `camp/apps/calibrations/core/processors/o3.py`
- Modify: `camp/apps/monitors/vozbox/tests.py`

- [ ] **Step 1: Write failing processor tests**

Append to `camp/apps/monitors/vozbox/tests.py`:
```python
from camp.apps.calibrations import processors as cal_processors


class O3VOZBoxProcessorTests(TestCase):
    def test_processor_is_registered(self):
        assert 'O3_VOZBox' in cal_processors

    def test_processor_name(self):
        assert cal_processors.O3_VOZBox.name == 'O3_VOZBox'

    def test_processor_entry_model_is_o3(self):
        assert cal_processors.O3_VOZBox.entry_model == entry_models.O3

    def test_processor_required_stage_is_raw(self):
        assert cal_processors.O3_VOZBox.required_stage == entry_models.O3.Stage.RAW

    def test_processor_next_stage_is_calibrated(self):
        assert cal_processors.O3_VOZBox.next_stage == entry_models.O3.Stage.CALIBRATED

    def test_processor_returns_none_when_no_calibration(self):
        monitor = VOZBox.objects.create(
            sensor_id='e00fce68test0001',
            name='Test O3',
            location='outside',
        )
        o3_entry = entry_models.O3.objects.create(
            monitor=monitor,
            location='outside',
            sensor='1',
            stage=entry_models.O3.Stage.RAW,
            value=25.0,
        )
        result = cal_processors.O3_VOZBox(o3_entry).run()
        assert result is None
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker compose run --rm test pytest camp/apps/monitors/vozbox/tests.py::O3VOZBoxProcessorTests -v
```
Expected: `AssertionError: assert 'O3_VOZBox' in ...` — processor doesn't exist yet.

- [ ] **Step 3: Implement O3_VOZBox processor**

`camp/apps/calibrations/core/processors/o3.py`:
```python
from decimal import Decimal

from camp.apps.entries.models import O3
from camp.apps.calibrations import processors
from .ml.linear import LinearExpressionProcessor


@processors.register()
class O3_VOZBox(LinearExpressionProcessor):
    entry_model = O3
    required_stage = O3.Stage.RAW
    next_stage = O3.Stage.CALIBRATED
    required_context = ['temperature', 'humidity']
    min_required_value = Decimal('0.0')
```

- [ ] **Step 4: Run processor tests**

```bash
docker compose run --rm test pytest camp/apps/monitors/vozbox/tests.py::O3VOZBoxProcessorTests -v
```
Expected: All 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add camp/apps/calibrations/core/processors/o3.py camp/apps/monitors/vozbox/tests.py
git commit -m "feat(vozbox): add O3_VOZBox calibration processor stub"
```

---

## Task 6: Tasks

**Files:**
- Create: `camp/apps/monitors/vozbox/tasks.py`
- Modify: `camp/apps/monitors/vozbox/tests.py`

- [ ] **Step 1: Write failing task tests**

Append to `camp/apps/monitors/vozbox/tests.py`:
```python
from camp.apps.monitors.vozbox.tasks import process_device


class ProcessDeviceTests(TestCase):
    def _make_rows(self, coreid, count=2):
        rows = []
        for i in range(count):
            rows.append({
                'timestamp': datetime(2025, 6, 9, i, 0, 0, tzinfo=timezone.utc),
                'pm1_a': 7.0, 'pm1_b': 4.0,
                'pm25_a': 10.0, 'pm25_b': 4.0,
                'pm10_a': 10.0, 'pm10_b': 4.0,
                'temperature': 36.0,
                'humidity': 26.0,
                'o3': 70.0,
                'o3_cal': None,
                'latitude': 36.785328,
                'longitude': -119.773125,
            })
        return rows

    def test_process_device_creates_monitor_on_first_encounter(self):
        coreid = 'e00fce68f12da1a0c5de6248'
        rows = self._make_rows(coreid)
        process_device(coreid, rows)
        assert VOZBox.objects.filter(sensor_id=coreid).exists()

    def test_process_device_uses_existing_monitor(self):
        coreid = 'e00fce68f12da1a0c5de6248'
        monitor = VOZBox.objects.create(
            sensor_id=coreid,
            name='Coalinga',
            location='outside',
        )
        rows = self._make_rows(coreid)
        process_device(coreid, rows)
        assert VOZBox.objects.filter(sensor_id=coreid).count() == 1
        monitor.refresh_from_db()
        assert monitor.name == 'Coalinga'

    def test_process_device_creates_entries(self):
        coreid = 'e00fce68f12da1a0c5de6248'
        rows = self._make_rows(coreid, count=1)
        process_device(coreid, rows)
        monitor = VOZBox.objects.get(sensor_id=coreid)
        assert entry_models.PM25.objects.filter(monitor=monitor).exists()
        assert entry_models.O3.objects.filter(monitor=monitor).exists()

    def test_process_device_deduplicates_rows(self):
        coreid = 'e00fce68f12da1a0c5de6248'
        rows = self._make_rows(coreid, count=1)
        process_device(coreid, rows)
        process_device(coreid, rows)   # second call with same rows
        monitor = VOZBox.objects.get(sensor_id=coreid)
        pm25_count = entry_models.PM25.objects.filter(monitor=monitor, sensor='a', stage='raw').count()
        assert pm25_count == 1   # no duplicates

    def test_process_device_skips_rows_before_latest(self):
        coreid = 'e00fce68f12da1a0c5de6248'
        rows = self._make_rows(coreid, count=3)
        process_device(coreid, rows[:2])   # process first 2
        process_device(coreid, rows)        # process all 3 (first 2 already exist)
        monitor = VOZBox.objects.get(sensor_id=coreid)
        pm25_count = entry_models.PM25.objects.filter(monitor=monitor, sensor='a', stage='raw').count()
        assert pm25_count == 3
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker compose run --rm test pytest camp/apps/monitors/vozbox/tests.py::ProcessDeviceTests -v
```
Expected: `ImportError` — `process_device` doesn't exist yet.

- [ ] **Step 3: Implement tasks.py**

`camp/apps/monitors/vozbox/tasks.py`:
```python
from datetime import timedelta

from django.utils import timezone

from django_huey import db_task, db_periodic_task
from huey import crontab

from camp.apps.entries import models as entry_models
from camp.apps.monitors.vozbox.api import VozBoxClient
from camp.apps.monitors.vozbox.models import VOZBox


@db_periodic_task(crontab(minute='*/10'), priority=50)
def import_realtime():
    start = timezone.now()
    print(f'\n=== VOZbox Import Start: {start.time()}\n')

    today = timezone.localdate()
    yesterday = today - timedelta(days=1)

    combined = {}
    with VozBoxClient() as client:
        for d in [yesterday, today]:
            data = client.get_daily_data(d)
            if data is None:
                continue
            for coreid, rows in data.items():
                combined.setdefault(coreid, []).extend(rows)

    for coreid, rows in combined.items():
        process_device.schedule([coreid, rows], delay=1, priority=40)

    end = timezone.now()
    print(f'\n=== VOZbox Import Done: {start.time()} - {end.time()} ({end - start})\n')


@db_task()
def process_device(coreid, rows):
    try:
        monitor = VOZBox.objects.get(sensor_id=coreid)
    except VOZBox.DoesNotExist:
        monitor = VOZBox(sensor_id=coreid)
        if rows:
            latest_row = max(rows, key=lambda r: r['timestamp'])
            monitor.update_data(latest_row)
        monitor.save()

    if not rows:
        return

    # Efficient cutoff: skip rows already in DB. validation_check() is the safety net.
    latest_ts = (entry_models.PM25.objects
        .filter(monitor=monitor, sensor='a', stage=entry_models.PM25.Stage.RAW)
        .order_by('-timestamp')
        .values_list('timestamp', flat=True)
        .first()
    )

    for row in sorted(rows, key=lambda r: r['timestamp']):
        if latest_ts and row['timestamp'] <= latest_ts:
            continue
        entries = monitor.create_entries(row)
        for entry in entries:
            monitor.process_entry_pipeline(entry)

    latest_row = max(rows, key=lambda r: r['timestamp'])
    monitor.update_data(latest_row)
    monitor.save()
```

- [ ] **Step 4: Run task tests**

```bash
docker compose run --rm test pytest camp/apps/monitors/vozbox/tests.py::ProcessDeviceTests -v
```
Expected: All 5 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add camp/apps/monitors/vozbox/tasks.py camp/apps/monitors/vozbox/tests.py
git commit -m "feat(vozbox): add import tasks"
```

---

## Task 7: Admin

**Files:**
- Create: `camp/apps/monitors/vozbox/admin.py`

No tests for admin registration.

- [ ] **Step 1: Implement admin.py**

`camp/apps/monitors/vozbox/admin.py`:
```python
from django.contrib.gis import admin

from camp.apps.monitors.admin import MonitorAdmin
from camp.apps.monitors.vozbox.models import VOZBox


@admin.register(VOZBox)
class VOZBoxAdmin(MonitorAdmin):
    list_display = MonitorAdmin.list_display[:]
    list_display.insert(1, 'sensor_id')

    search_fields = MonitorAdmin.search_fields[:]
    search_fields.append('sensor_id')
```

- [ ] **Step 2: Verify admin loads without errors**

```bash
docker compose run --rm web python manage.py check
```
Expected: `System check identified no issues (0 silenced).`

- [ ] **Step 3: Commit**

```bash
git add camp/apps/monitors/vozbox/admin.py
git commit -m "feat(vozbox): add admin registration"
```

---

## Task 8: Management command

**Files:**
- Create: `camp/apps/monitors/vozbox/management/commands/import_vozbox_cal.py`
- Modify: `camp/apps/monitors/vozbox/tests.py`

- [ ] **Step 1: Write failing management command tests**

Append to `camp/apps/monitors/vozbox/tests.py`:
```python
from io import StringIO
from datetime import date as date_type
from unittest.mock import patch, MagicMock
from django.core.management import call_command


class ImportVozboxCalTests(TestCase):
    def setUp(self):
        self.monitor = VOZBox.objects.create(
            sensor_id='e00fce682bbf742cd0b6768a',
            name='Lost Hills',
            location='outside',
        )

    def _cal_rows(self):
        return {
            'e00fce682bbf742cd0b6768a': [{
                'timestamp': datetime(2025, 6, 20, 15, 0, 0, tzinfo=timezone.utc),
                'pm25_a': 5.0, 'pm25_b': 4.0,
                'pm10_a': 6.0, 'pm10_b': 4.0,
                'pm1_a': None, 'pm1_b': None,
                'temperature': 16.0,
                'humidity': 54.0,
                'o3': 26.981,
                'o3_cal': 23.127,
                'latitude': 36.785343,
                'longitude': -119.773056,
            }],
        }

    @patch('camp.apps.monitors.vozbox.management.commands.import_vozbox_cal.VozBoxClient')
    def test_creates_calibrated_o3_entry(self, MockClient):
        instance = MockClient.return_value.__enter__.return_value
        instance.list_cal_files.return_value = [(date_type(2025, 6, 20), 15)]
        instance.get_cal_data.return_value = self._cal_rows()

        out = StringIO()
        call_command('import_vozbox_cal', stdout=out)

        assert entry_models.O3.objects.filter(
            monitor=self.monitor,
            stage=entry_models.O3.Stage.CALIBRATED,
            sensor='1',
        ).exists()

    @patch('camp.apps.monitors.vozbox.management.commands.import_vozbox_cal.VozBoxClient')
    def test_skips_unknown_coreids(self, MockClient):
        rows = self._cal_rows()
        rows['unknown_coreid_xyz'] = rows['e00fce682bbf742cd0b6768a']
        instance = MockClient.return_value.__enter__.return_value
        instance.list_cal_files.return_value = [(date_type(2025, 6, 20), 15)]
        instance.get_cal_data.return_value = rows

        out = StringIO()
        call_command('import_vozbox_cal', stdout=out)

        assert 'unknown_coreid_xyz' in out.getvalue()

    @patch('camp.apps.monitors.vozbox.management.commands.import_vozbox_cal.VozBoxClient')
    def test_date_range_filter(self, MockClient):
        instance = MockClient.return_value.__enter__.return_value
        instance.list_cal_files.return_value = [
            (date_type(2025, 6, 19), 12),
            (date_type(2025, 6, 20), 15),
            (date_type(2025, 6, 21), 8),
        ]
        instance.get_cal_data.return_value = {}

        call_command('import_vozbox_cal', start='2025-06-20', end='2025-06-20')

        assert instance.get_cal_data.call_count == 1
        instance.get_cal_data.assert_called_once_with(date_type(2025, 6, 20), 15)

    @patch('camp.apps.monitors.vozbox.management.commands.import_vozbox_cal.VozBoxClient')
    def test_skips_row_when_o3_cal_is_none(self, MockClient):
        rows = self._cal_rows()
        rows['e00fce682bbf742cd0b6768a'][0]['o3_cal'] = None
        instance = MockClient.return_value.__enter__.return_value
        instance.list_cal_files.return_value = [(date_type(2025, 6, 20), 15)]
        instance.get_cal_data.return_value = rows

        call_command('import_vozbox_cal')

        assert not entry_models.O3.objects.filter(
            monitor=self.monitor,
            stage=entry_models.O3.Stage.CALIBRATED,
        ).exists()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
docker compose run --rm test pytest camp/apps/monitors/vozbox/tests.py::ImportVozboxCalTests -v
```
Expected: `CommandError` or `ModuleNotFoundError` — command doesn't exist yet.

- [ ] **Step 3: Implement the management command**

`camp/apps/monitors/vozbox/management/commands/import_vozbox_cal.py`:
```python
from datetime import date

from django.core.management.base import BaseCommand

from camp.apps.entries import models as entry_models
from camp.apps.monitors.vozbox.api import VozBoxClient
from camp.apps.monitors.vozbox.models import VOZBox


class Command(BaseCommand):
    help = 'Backfill calibrated O3 data from moospmV3_cal CSVs on GitHub'

    def add_arguments(self, parser):
        parser.add_argument('--start', type=str, default=None, help='Start date YYYY-MM-DD (inclusive)')
        parser.add_argument('--end', type=str, default=None, help='End date YYYY-MM-DD (inclusive)')

    def handle(self, *args, **options):
        start = date.fromisoformat(options['start']) if options['start'] else None
        end = date.fromisoformat(options['end']) if options['end'] else None

        with VozBoxClient() as client:
            cal_files = client.list_cal_files()

            for cal_date, hour_utc in sorted(cal_files):
                if start and cal_date < start:
                    continue
                if end and cal_date > end:
                    continue

                data = client.get_cal_data(cal_date, hour_utc)
                if not data:
                    continue

                self.stdout.write(f'Processing {cal_date} T{hour_utc:02d}...')

                for coreid, rows in data.items():
                    try:
                        monitor = VOZBox.objects.get(sensor_id=coreid)
                    except VOZBox.DoesNotExist:
                        self.stdout.write(f'  Skipping unknown coreid: {coreid}')
                        continue

                    for row in rows:
                        o3_cal = row.get('o3_cal')
                        if o3_cal is None:
                            continue
                        monitor.create_entry(
                            entry_models.O3,
                            timestamp=row['timestamp'],
                            sensor='1',
                            stage=entry_models.O3.Stage.CALIBRATED,
                            value=o3_cal,
                        )

                    monitor.save()
```

- [ ] **Step 4: Run management command tests**

```bash
docker compose run --rm test pytest camp/apps/monitors/vozbox/tests.py::ImportVozboxCalTests -v
```
Expected: All 4 tests PASS.

- [ ] **Step 5: Run the full test suite for the vozbox app**

```bash
docker compose run --rm test pytest camp/apps/monitors/vozbox/tests.py -v
```
Expected: All tests PASS (should be 28 total).

- [ ] **Step 6: Run the broader test suite to check for regressions**

```bash
docker compose run --rm test pytest camp/apps/monitors/ -v
```
Expected: All tests PASS.

- [ ] **Step 7: Commit**

```bash
git add camp/apps/monitors/vozbox/management/commands/import_vozbox_cal.py camp/apps/monitors/vozbox/tests.py
git commit -m "feat(vozbox): add import_vozbox_cal management command"
```

---

## Self-review checklist

- [x] **Client library** (spec §3): `VozBoxClient` with context manager, `GITHUB_API_TOKEN`, temp dir, `parse_csv`, `get_daily_data`, `get_cal_data`, `list_daily_files`, `list_cal_files` — all in Task 2/3.
- [x] **Monitor model** (spec §4): `VOZBox` with correct `ENTRY_CONFIG`, `sensor_id` CharField, `update_data`, `create_entries`, `supports_health_checks` — Task 4.
- [x] **O3 calibration processor** (spec §5): `O3_VOZBox` stub registered, inactive until `DefaultCalibration` exists — Task 5.
- [x] **Realtime task** (spec §6): `import_realtime` every 10 min, `process_device` with dedup cutoff — Task 6.
- [x] **Management command** (spec §7): `import_vozbox_cal --start/--end`, skips unknown coreids, creates CALIBRATED O3 at `processor=''` — Task 8.
- [x] **Admin** (spec §8): `VOZBoxAdmin` with sensor_id in list — Task 7.
- [x] **INSTALLED_APPS**: Task 1.
- [x] **`GITHUB_API_TOKEN` setting**: referenced in `api.py` Task 2, no hardcoded `VOZBOX_GITHUB_TOKEN`.
- [x] **`processor=''` for external O3**: `create_entry` is called without passing `processor`, so it defaults to `''`. `update_latest_entry` will track these until a `DefaultCalibration` record exists for `(VOZBox, O3)`. ✓
- [x] **No `LCSMixin`**: `VOZBox` inherits `Monitor` directly with `sensor_id = CharField`. ✓
- [x] **`PM10` model = PM1.0 readings**: mapped from `m_PM1_ATM`/`m_PM1_b`. ✓
