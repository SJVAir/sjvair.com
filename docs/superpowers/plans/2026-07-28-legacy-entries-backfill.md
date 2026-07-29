# Legacy Entries Backfill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a resumable, chunked backfill system that (1) copies legacy `Entry` rows into the new `entries` app as RAW-stage entries wherever they're missing — including interior gaps, not just at the start/end of a monitor's history — and (2) drives those RAW entries (and any other historically-stuck RAW entries) through the existing correction/cleaning/calibration pipeline, plus a one-time repair for a known unit-conversion bug in previously-migrated `Pressure` data.

**Architecture:** Two independent DB-tracked job models (`EntryBackfillJob`, `PipelineBackfillJob`), each driven by a per-minute Huey periodic "tick" task that fans out one task per monitor per chunk and never blocks waiting on them — mirroring `SummaryBackfillJob` (`camp/apps/summaries/models.py`, `camp/apps/summaries/tasks.py`). A shared idempotency fix in `BaseProcessor.run()` makes pipeline reprocessing safe to resume from any partial state. All new entry inserts and pipeline advances are safe to re-run (upsert / existing-entry-return semantics).

**Tech Stack:** Django 5.2, PostgreSQL, `django-huey` (Huey task queue, `MemoryHuey`/immediate mode in tests), `django_sqids`, `model_utils.TimeStampedModel`, pytest-style assertions under `django.test.TestCase`.

## Global Constraints

- New models use sqids: `sqid = SqidsField(alphabet=shuffle_alphabet('app.ModelName'))` (project convention).
- Tests use plain `assert` statements, not `self.assertFoo()`.
- Timezone is always `America/Los_Angeles`; use `camp.utils.datetime.make_aware` for aware datetimes in tests.
- No `git add -A` — stage files explicitly. Never commit directly to `main` (this work happens on `feature/legacy-entries-backfill`, already checked out).
- Run tests via `docker compose run --rm test pytest <path> -v`.
- Spec: `docs/superpowers/specs/2026-07-28-legacy-entries-backfill-design.md` — refer back to it for the field-mapping table and full rationale; this plan implements it exactly.

---

## File Structure

| File | Responsibility |
|---|---|
| `camp/apps/monitors/legacy_backfill.py` | New. `LEGACY_BACKFILL_MAP`, pure mapping/construction/gap-detection/chunking helpers for both phases. No Huey/job-model coupling. |
| `camp/apps/monitors/models.py` | Modify. Add `EntryBackfillJob`, `PipelineBackfillJob`. Remove `get_entry_migration_status()`. |
| `camp/apps/monitors/migrations/0037_entrybackfilljob.py` | New. |
| `camp/apps/monitors/migrations/0038_pipelinebackfilljob.py` | New. |
| `camp/apps/monitors/tasks.py` | Modify. Add both jobs' tick + per-monitor-chunk tasks. |
| `camp/apps/monitors/admin.py` | Modify. Register both job models. |
| `camp/apps/monitors/management/commands/backfill_legacy_entries.py` | New. start/status/cancel for `EntryBackfillJob`. |
| `camp/apps/monitors/management/commands/reprocess_legacy_pipeline.py` | New. start/status/cancel for `PipelineBackfillJob`. |
| `camp/apps/monitors/management/commands/fix_purpleair_pressure.py` | New. One-time Pressure repair. |
| `camp/apps/calibrations/core/processors/base.py` | Modify. `BaseProcessor.run()` idempotency fix. |
| `camp/apps/monitors/test_legacy_backfill.py` | New. All tests for the above except the processor fix. |
| `camp/apps/calibrations/core/processors/test_base.py` | New (or add to existing processor test file if one exists at that path — check before creating). Idempotency fix tests. |

---

### Task 1: Legacy field mapping table and RAW entry construction

**Files:**
- Create: `camp/apps/monitors/legacy_backfill.py`
- Test: `camp/apps/monitors/test_legacy_backfill.py`

**Interfaces:**
- Produces: `LEGACY_BACKFILL_MAP` (dict, `{MonitorClass: {EntryModel: mapping_dict}}`), `build_raw_entry(monitor, legacy_entry, entry_model, mapping) -> EntryModel instance or None`.

- [ ] **Step 1: Write the failing tests**

```python
# camp/apps/monitors/test_legacy_backfill.py
from decimal import Decimal

from django.test import TestCase

from camp.apps.entries import models as entry_models
from camp.apps.monitors.legacy_backfill import LEGACY_BACKFILL_MAP, build_raw_entry
from camp.apps.monitors.models import Entry
from camp.apps.monitors.airnow.models import AirNow
from camp.apps.monitors.aqview.models import AQview
from camp.apps.monitors.bam.models import BAM1022
from camp.apps.monitors.purpleair.models import PurpleAir


def _legacy_entry(monitor, **kwargs):
    defaults = {
        'monitor': monitor,
        'sensor': '',
        'location': Entry._meta.get_field('location').choices[0][0],
    }
    defaults.update(kwargs)
    return Entry(**defaults)


class BuildRawEntryPurpleAirTests(TestCase):
    def setUp(self):
        self.monitor = PurpleAir(name='Test PurpleAir', sensor_id=1, location='outside')

    def test_pm25_uses_reported_only_not_calibrated(self):
        legacy = _legacy_entry(
            self.monitor, sensor='a', pm25=Decimal('12.00'), pm25_reported=Decimal('9.50'),
        )
        mapping = LEGACY_BACKFILL_MAP[PurpleAir][entry_models.PM25]
        entry = build_raw_entry(self.monitor, legacy, entry_models.PM25, mapping)
        assert entry.value == Decimal('9.50')
        assert entry.sensor == 'a'

    def test_pm25_returns_none_when_reported_missing(self):
        legacy = _legacy_entry(self.monitor, sensor='a', pm25=Decimal('12.00'), pm25_reported=None)
        mapping = LEGACY_BACKFILL_MAP[PurpleAir][entry_models.PM25]
        assert build_raw_entry(self.monitor, legacy, entry_models.PM25, mapping) is None

    def test_particulates_copies_all_fields_directly(self):
        legacy = _legacy_entry(
            self.monitor, sensor='b',
            particles_03um=Decimal('1.1'), particles_05um=Decimal('2.2'),
            particles_10um=Decimal('3.3'), particles_25um=Decimal('4.4'),
            particles_50um=Decimal('5.5'), particles_100um=Decimal('6.6'),
        )
        mapping = LEGACY_BACKFILL_MAP[PurpleAir][entry_models.Particulates]
        entry = build_raw_entry(self.monitor, legacy, entry_models.Particulates, mapping)
        assert entry.particles_03um == Decimal('1.1')
        assert entry.particles_100um == Decimal('6.6')
        assert entry.sensor == 'b'

    def test_particulates_returns_none_when_any_field_missing(self):
        legacy = _legacy_entry(
            self.monitor, sensor='b',
            particles_03um=Decimal('1.1'), particles_05um=None,
            particles_10um=Decimal('3.3'), particles_25um=Decimal('4.4'),
            particles_50um=Decimal('5.5'), particles_100um=Decimal('6.6'),
        )
        mapping = LEGACY_BACKFILL_MAP[PurpleAir][entry_models.Particulates]
        assert build_raw_entry(self.monitor, legacy, entry_models.Particulates, mapping) is None

    def test_temperature_and_humidity_and_pressure_collapse_sensor_to_blank(self):
        legacy = _legacy_entry(
            self.monitor, sensor='a', fahrenheit=Decimal('70.5'),
            humidity=Decimal('40.0'), pressure=Decimal('1013.25'),
        )
        temp = build_raw_entry(
            self.monitor, legacy, entry_models.Temperature,
            LEGACY_BACKFILL_MAP[PurpleAir][entry_models.Temperature],
        )
        humidity = build_raw_entry(
            self.monitor, legacy, entry_models.Humidity,
            LEGACY_BACKFILL_MAP[PurpleAir][entry_models.Humidity],
        )
        assert temp.sensor == ''
        assert temp.fahrenheit == Decimal('70.5')
        assert humidity.sensor == ''
        assert humidity.value == Decimal('40.0')

    def test_pressure_hpa_converted_to_mmhg(self):
        legacy = _legacy_entry(self.monitor, sensor='a', pressure=Decimal('1013.25'))
        mapping = LEGACY_BACKFILL_MAP[PurpleAir][entry_models.Pressure]
        entry = build_raw_entry(self.monitor, legacy, entry_models.Pressure, mapping)
        # 1013.25 hPa -> mmHg via the model's own hpa setter (1 hPa = 1/1.33322 mmHg)
        expected = (Decimal('1013.25') / Decimal('1.33322')).quantize(Decimal('0.01'))
        assert entry.value == expected

    def test_raw_entry_uses_legacy_position_and_location(self):
        legacy = _legacy_entry(self.monitor, sensor='a', pm25_reported=Decimal('5.0'), location='inside')
        mapping = LEGACY_BACKFILL_MAP[PurpleAir][entry_models.PM25]
        entry = build_raw_entry(self.monitor, legacy, entry_models.PM25, mapping)
        assert entry.location == 'inside'
        assert entry.stage == entry_models.PM25.Stage.RAW
        assert entry.processor == ''


class BuildRawEntryCoalesceTests(TestCase):
    def test_airnow_prefers_reported_falls_back_to_pm25(self):
        monitor = AirNow(name='Test AirNow', location='outside')
        legacy = _legacy_entry(monitor, pm25=Decimal('8.0'), pm25_reported=None)
        mapping = LEGACY_BACKFILL_MAP[AirNow][entry_models.PM25]
        entry = build_raw_entry(monitor, legacy, entry_models.PM25, mapping)
        assert entry.value == Decimal('8.0')

    def test_airnow_prefers_reported_when_both_present(self):
        monitor = AirNow(name='Test AirNow', location='outside')
        legacy = _legacy_entry(monitor, pm25=Decimal('8.0'), pm25_reported=Decimal('7.5'))
        mapping = LEGACY_BACKFILL_MAP[AirNow][entry_models.PM25]
        entry = build_raw_entry(monitor, legacy, entry_models.PM25, mapping)
        assert entry.value == Decimal('7.5')

    def test_aqview_coalesce_same_as_airnow(self):
        monitor = AQview(name='Test AQview', location='outside')
        legacy = _legacy_entry(monitor, pm25=Decimal('3.0'), pm25_reported=None)
        mapping = LEGACY_BACKFILL_MAP[AQview][entry_models.PM25]
        entry = build_raw_entry(monitor, legacy, entry_models.PM25, mapping)
        assert entry.value == Decimal('3.0')


class BuildRawEntryBamTests(TestCase):
    def setUp(self):
        self.monitor = BAM1022(name='Test BAM', location='outside')

    def test_pm25_coalesces_and_skips_sentinel(self):
        mapping = LEGACY_BACKFILL_MAP[BAM1022][entry_models.PM25]
        legacy = _legacy_entry(self.monitor, pm25=Decimal('99999'), pm25_reported=None)
        assert build_raw_entry(self.monitor, legacy, entry_models.PM25, mapping) is None

    def test_pm25_sentinel_check_uses_pm25_not_reported(self):
        mapping = LEGACY_BACKFILL_MAP[BAM1022][entry_models.PM25]
        legacy = _legacy_entry(self.monitor, pm25=Decimal('4.2'), pm25_reported=Decimal('4.2'))
        entry = build_raw_entry(self.monitor, legacy, entry_models.PM25, mapping)
        assert entry.value == Decimal('4.2')

    def test_pressure_mmhg_copied_directly_no_conversion(self):
        mapping = LEGACY_BACKFILL_MAP[BAM1022][entry_models.Pressure]
        legacy = _legacy_entry(self.monitor, pressure=Decimal('750.00'))
        entry = build_raw_entry(self.monitor, legacy, entry_models.Pressure, mapping)
        assert entry.value == Decimal('750.00')

    def test_celsius_converted_to_fahrenheit(self):
        mapping = LEGACY_BACKFILL_MAP[BAM1022][entry_models.Temperature]
        legacy = _legacy_entry(self.monitor, celsius=Decimal('20.0'))
        entry = build_raw_entry(self.monitor, legacy, entry_models.Temperature, mapping)
        # 20C -> 68F via the model's own celsius setter
        assert entry.value == Decimal('68.0')
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose run --rm test pytest camp/apps/monitors/test_legacy_backfill.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'camp.apps.monitors.legacy_backfill'`

- [ ] **Step 3: Write the implementation**

```python
# camp/apps/monitors/legacy_backfill.py
'''
Field mapping and pure construction logic for backfilling legacy `Entry` rows
(camp/apps/monitors/models.py) into the new `entries` app, RAW stage only.
See docs/superpowers/specs/2026-07-28-legacy-entries-backfill-design.md.
'''
from camp.apps.entries import models as entry_models


def _bam_pm25_sentinel(legacy_entry):
    return legacy_entry.pm25 == 99999


LEGACY_BACKFILL_MAP = {}


def _register(monitor_cls, mapping):
    LEGACY_BACKFILL_MAP[monitor_cls] = mapping


def _load_map():
    from camp.apps.monitors.purpleair.models import PurpleAir
    from camp.apps.monitors.airnow.models import AirNow
    from camp.apps.monitors.aqview.models import AQview
    from camp.apps.monitors.bam.models import BAM1022

    _register(PurpleAir, {
        entry_models.PM25: {'source': 'pm25_reported', 'target': 'value', 'per_sensor': True},
        entry_models.PM10: {'source': 'pm10', 'target': 'value', 'per_sensor': True},
        entry_models.PM100: {'source': 'pm100', 'target': 'value', 'per_sensor': True},
        entry_models.Particulates: {
            'source': [
                'particles_03um', 'particles_05um', 'particles_10um',
                'particles_25um', 'particles_50um', 'particles_100um',
            ],
            'per_sensor': True,
        },
        entry_models.Temperature: {'source': 'fahrenheit', 'target': 'fahrenheit', 'per_sensor': False},
        entry_models.Humidity: {'source': 'humidity', 'target': 'value', 'per_sensor': False},
        entry_models.Pressure: {'source': 'pressure', 'target': 'hpa', 'per_sensor': False},
    })

    _register(AirNow, {
        entry_models.PM25: {'source': ('pm25_reported', 'pm25'), 'target': 'value', 'per_sensor': False},
        entry_models.PM100: {'source': 'pm100', 'target': 'value', 'per_sensor': False},
        entry_models.O3: {'source': 'ozone', 'target': 'value', 'per_sensor': False},
    })

    _register(AQview, {
        entry_models.PM25: {'source': ('pm25_reported', 'pm25'), 'target': 'value', 'per_sensor': False},
    })

    _register(BAM1022, {
        entry_models.PM25: {
            'source': ('pm25_reported', 'pm25'), 'target': 'value', 'per_sensor': False,
            'skip_if': _bam_pm25_sentinel,
        },
        entry_models.Temperature: {'source': 'celsius', 'target': 'celsius', 'per_sensor': False},
        entry_models.Humidity: {'source': 'humidity', 'target': 'value', 'per_sensor': False},
        entry_models.Pressure: {'source': 'pressure', 'target': 'mmhg', 'per_sensor': False},
    })


_load_map()


def build_raw_entry(monitor, legacy_entry, entry_model, mapping):
    '''
    Given a legacy Entry row and its mapping (one value of a LEGACY_BACKFILL_MAP
    entry), return an unsaved `entry_model` RAW instance, or None if the source
    data is missing or explicitly skipped.
    '''
    skip_if = mapping.get('skip_if')
    if skip_if and skip_if(legacy_entry):
        return None

    source = mapping['source']
    target = mapping.get('target')

    if isinstance(source, list):
        values = {}
        for field_name in source:
            value = getattr(legacy_entry, field_name)
            if value is None:
                return None
            values[field_name] = value
    else:
        if isinstance(source, tuple):
            value = None
            for field_name in source:
                value = getattr(legacy_entry, field_name)
                if value is not None:
                    break
        else:
            value = getattr(legacy_entry, source)

        if value is None:
            return None

        values = {target: value}

    sensor = legacy_entry.sensor if mapping.get('per_sensor') else ''

    entry = entry_model(
        monitor=monitor,
        timestamp=legacy_entry.timestamp,
        sensor=sensor,
        position=legacy_entry.position,
        location=legacy_entry.location,
        stage=entry_model.Stage.RAW,
        processor='',
    )
    for field_name, value in values.items():
        setattr(entry, field_name, value)

    return entry
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose run --rm test pytest camp/apps/monitors/test_legacy_backfill.py -v`
Expected: PASS (all tests in the three classes above)

- [ ] **Step 5: Commit**

```bash
git add camp/apps/monitors/legacy_backfill.py camp/apps/monitors/test_legacy_backfill.py
git commit -m "feat(monitors): add legacy entry field mapping and RAW entry construction"
```

---

### Task 2: Chunking and gap-detection helpers (RAW phase)

**Files:**
- Modify: `camp/apps/monitors/legacy_backfill.py`
- Test: `camp/apps/monitors/test_legacy_backfill.py`

**Interfaces:**
- Consumes: `LEGACY_BACKFILL_MAP`, `build_raw_entry` (Task 1).
- Produces: `chunk_start_for(cursor, range_start, chunk_days=7) -> datetime`, `find_missing_raw_entries(monitor, entry_model, mapping, chunk_start, chunk_end) -> list[EntryModel instance]`, `monitors_with_legacy_data_in(chunk_start, chunk_end) -> list[monitor_id]`, `eligible_monitor_classes() -> list[MonitorClass]`.

- [ ] **Step 1: Write the failing tests**

```python
# append to camp/apps/monitors/test_legacy_backfill.py
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from camp.utils.datetime import make_aware
from camp.apps.monitors.legacy_backfill import (
    chunk_start_for, find_missing_raw_entries, monitors_with_legacy_data_in,
)


def _ts(*args):
    from datetime import datetime
    return make_aware(datetime(*args), settings.DEFAULT_TIMEZONE)


class ChunkStartForTests(TestCase):
    def test_steps_back_by_chunk_days(self):
        cursor = _ts(2023, 7, 15)
        range_start = _ts(2020, 1, 1)
        assert chunk_start_for(cursor, range_start, chunk_days=7) == cursor - timedelta(days=7)

    def test_clamps_to_range_start(self):
        cursor = _ts(2020, 1, 4)
        range_start = _ts(2020, 1, 1)
        assert chunk_start_for(cursor, range_start, chunk_days=7) == range_start


class FindMissingRawEntriesTests(TestCase):
    fixtures = ['purple-air.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.first()
        self.window_start = _ts(2023, 1, 1)
        self.window_end = _ts(2023, 1, 8)

    def test_finds_legacy_row_with_no_new_entry(self):
        Entry.objects.create(
            monitor=self.monitor, sensor='a', timestamp=self.window_start + timedelta(hours=1),
            location=self.monitor.location, pm25_reported=Decimal('5.0'),
        )
        mapping = LEGACY_BACKFILL_MAP[PurpleAir][entry_models.PM25]
        missing = find_missing_raw_entries(
            self.monitor, entry_models.PM25, mapping, self.window_start, self.window_end,
        )
        assert len(missing) == 1
        assert missing[0].value == Decimal('5.0')

    def test_skips_legacy_row_that_already_has_a_new_entry(self):
        ts = self.window_start + timedelta(hours=1)
        Entry.objects.create(
            monitor=self.monitor, sensor='a', timestamp=ts,
            location=self.monitor.location, pm25_reported=Decimal('5.0'),
        )
        entry_models.PM25.objects.create(
            monitor=self.monitor, sensor='a', timestamp=ts, location=self.monitor.location,
            stage=entry_models.PM25.Stage.RAW, processor='', value=Decimal('5.0'),
        )
        mapping = LEGACY_BACKFILL_MAP[PurpleAir][entry_models.PM25]
        missing = find_missing_raw_entries(
            self.monitor, entry_models.PM25, mapping, self.window_start, self.window_end,
        )
        assert missing == []

    def test_detects_interior_gap_not_just_head_or_tail(self):
        # Three legacy rows; only the middle one is missing its new-entry counterpart.
        timestamps = [self.window_start + timedelta(hours=h) for h in (1, 2, 3)]
        for i, ts in enumerate(timestamps):
            Entry.objects.create(
                monitor=self.monitor, sensor='a', timestamp=ts,
                location=self.monitor.location, pm25_reported=Decimal(f'{i}.0'),
            )
        for i, ts in enumerate(timestamps):
            if i == 1:
                continue  # leave the middle one un-migrated
            entry_models.PM25.objects.create(
                monitor=self.monitor, sensor='a', timestamp=ts, location=self.monitor.location,
                stage=entry_models.PM25.Stage.RAW, processor='', value=Decimal(f'{i}.0'),
            )
        mapping = LEGACY_BACKFILL_MAP[PurpleAir][entry_models.PM25]
        missing = find_missing_raw_entries(
            self.monitor, entry_models.PM25, mapping, self.window_start, self.window_end,
        )
        assert len(missing) == 1
        assert missing[0].timestamp == timestamps[1]

    def test_per_sensor_false_dedups_across_a_and_b_rows(self):
        ts = self.window_start + timedelta(hours=1)
        for sensor in ('a', 'b'):
            Entry.objects.create(
                monitor=self.monitor, sensor=sensor, timestamp=ts,
                location=self.monitor.location, humidity=Decimal('40.0'),
            )
        mapping = LEGACY_BACKFILL_MAP[PurpleAir][entry_models.Humidity]
        missing = find_missing_raw_entries(
            self.monitor, entry_models.Humidity, mapping, self.window_start, self.window_end,
        )
        assert len(missing) == 1
        assert missing[0].sensor == ''


class MonitorsWithLegacyDataInTests(TestCase):
    fixtures = ['purple-air.yaml']

    def test_finds_monitor_with_legacy_data_in_window(self):
        monitor = PurpleAir.objects.first()
        window_start = _ts(2023, 1, 1)
        window_end = _ts(2023, 1, 8)
        Entry.objects.create(
            monitor=monitor, sensor='a', timestamp=window_start + timedelta(hours=1),
            location=monitor.location, pm25_reported=Decimal('5.0'),
        )
        ids = monitors_with_legacy_data_in(window_start, window_end)
        assert monitor.pk in ids

    def test_excludes_monitor_with_no_data_in_window(self):
        monitor = PurpleAir.objects.first()
        window_start = _ts(2023, 1, 1)
        window_end = _ts(2023, 1, 8)
        ids = monitors_with_legacy_data_in(window_start, window_end)
        assert monitor.pk not in ids
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose run --rm test pytest camp/apps/monitors/test_legacy_backfill.py -v`
Expected: FAIL with `ImportError: cannot import name 'chunk_start_for'`

- [ ] **Step 3: Write the implementation**

```python
# append to camp/apps/monitors/legacy_backfill.py
from datetime import timedelta

from django.db.models import Exists, OuterRef


def eligible_monitor_classes():
    return list(LEGACY_BACKFILL_MAP.keys())


def chunk_start_for(cursor, range_start, chunk_days=7):
    return max(cursor - timedelta(days=chunk_days), range_start)


def _source_fields(mapping):
    source = mapping['source']
    if isinstance(source, list):
        return list(source)
    if isinstance(source, tuple):
        return list(source)
    return [source]


def find_missing_raw_entries(monitor, entry_model, mapping, chunk_start, chunk_end):
    '''
    Returns unsaved entry_model instances for legacy Entry rows in the window
    that have no corresponding RAW entry yet. Safe to call repeatedly.
    '''
    from django.db.models import Q
    from camp.apps.monitors.models import Entry

    field_filter = Q()
    for field_name in _source_fields(mapping):
        field_filter |= Q(**{f'{field_name}__isnull': False})

    legacy_qs = Entry.objects.filter(
        field_filter,
        monitor=monitor,
        timestamp__gte=chunk_start,
        timestamp__lt=chunk_end,
    )

    existing_keys = set(
        entry_model.objects.filter(
            monitor=monitor,
            stage=entry_model.Stage.RAW,
            timestamp__gte=chunk_start,
            timestamp__lt=chunk_end,
        ).values_list('timestamp', 'sensor')
    )

    seen = set()
    missing = []
    for legacy_entry in legacy_qs:
        entry = build_raw_entry(monitor, legacy_entry, entry_model, mapping)
        if entry is None:
            continue
        key = (entry.timestamp, entry.sensor)
        if key in existing_keys or key in seen:
            continue
        seen.add(key)
        missing.append(entry)

    return missing


def monitors_with_legacy_data_in(chunk_start, chunk_end):
    '''
    Returns pks of monitors (of the eligible types) with at least one legacy
    Entry row in [chunk_start, chunk_end).
    '''
    from camp.apps.monitors.models import Entry

    entries_in_range = Entry.objects.filter(
        monitor=OuterRef('pk'),
        timestamp__gte=chunk_start,
        timestamp__lt=chunk_end,
    )

    monitor_ids = set()
    for monitor_cls in eligible_monitor_classes():
        ids = (monitor_cls.objects
            .annotate(has_legacy=Exists(entries_in_range))
            .filter(has_legacy=True)
            .values_list('pk', flat=True))
        monitor_ids.update(ids)
    return list(monitor_ids)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose run --rm test pytest camp/apps/monitors/test_legacy_backfill.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add camp/apps/monitors/legacy_backfill.py camp/apps/monitors/test_legacy_backfill.py
git commit -m "feat(monitors): add chunking and gap-detection helpers for legacy entry backfill"
```

---

### Task 3: `EntryBackfillJob` model, migration, and admin

**Files:**
- Modify: `camp/apps/monitors/models.py`
- Create: `camp/apps/monitors/migrations/0037_entrybackfilljob.py`
- Modify: `camp/apps/monitors/admin.py`
- Test: `camp/apps/monitors/test_legacy_backfill.py`

**Interfaces:**
- Produces: `EntryBackfillJob` model with `State` choices (`RUNNING`, `PAUSED`, `DONE`, `FAILED`), fields `sqid, state, cursor, chunk_start, chunk_days, range_start, range_end, pending_tasks, batch_id, phase_started_at, locked_at, consecutive_failures, last_error, raw_entries_created, created, modified`.

- [ ] **Step 1: Write the failing test**

```python
# append to camp/apps/monitors/test_legacy_backfill.py
from camp.apps.monitors.models import EntryBackfillJob


class EntryBackfillJobTests(TestCase):
    def test_defaults(self):
        job = EntryBackfillJob.objects.create(
            cursor=_ts(2023, 1, 8), range_start=_ts(2020, 1, 1), range_end=_ts(2023, 1, 8),
        )
        assert job.state == EntryBackfillJob.State.RUNNING
        assert job.chunk_days == 7
        assert job.pending_tasks == 0
        assert job.batch_id == 0
        assert job.raw_entries_created == 0
        assert job.sqid
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose run --rm test pytest camp/apps/monitors/test_legacy_backfill.py::EntryBackfillJobTests -v`
Expected: FAIL with `ImportError: cannot import name 'EntryBackfillJob'`

- [ ] **Step 3: Write the model, migration, and admin registration**

Add near the bottom of `camp/apps/monitors/models.py` (after the `Entry` class, before `LCSMixin`), and add the import at the top of the file alongside the existing `model_utils` imports:

```python
# camp/apps/monitors/models.py — add to the existing import block
from django_sqids import SqidsField, shuffle_alphabet
```

```python
# camp/apps/monitors/models.py — new model
class EntryBackfillJob(TimeStampedModel):
    '''
    Tracks progress of the legacy Entry -> entries app RAW-stage backfill.
    See docs/superpowers/specs/2026-07-28-legacy-entries-backfill-design.md.
    '''
    class State(models.TextChoices):
        RUNNING = 'running', _('Running')
        PAUSED = 'paused', _('Paused')
        DONE = 'done', _('Done')
        FAILED = 'failed', _('Failed')

    sqid = SqidsField(alphabet=shuffle_alphabet('monitors.EntryBackfillJob'))

    state = models.CharField(_('state'), max_length=10, choices=State.choices, default=State.RUNNING)

    cursor = models.DateTimeField(_('cursor'))
    chunk_start = models.DateTimeField(_('chunk start'), null=True, blank=True)
    chunk_days = models.PositiveSmallIntegerField(_('chunk days'), default=7)
    range_start = models.DateTimeField(_('range start'))
    range_end = models.DateTimeField(_('range end'))

    pending_tasks = models.PositiveIntegerField(_('pending tasks'), default=0)
    batch_id = models.PositiveIntegerField(_('batch id'), default=0)
    phase_started_at = models.DateTimeField(_('phase started at'), null=True, blank=True)
    locked_at = models.DateTimeField(_('locked at'), null=True, blank=True)

    consecutive_failures = models.PositiveSmallIntegerField(_('consecutive failures'), default=0)
    last_error = models.TextField(_('last error'), blank=True, default='')

    raw_entries_created = models.PositiveIntegerField(_('raw entries created'), default=0)

    def __str__(self):
        return f'{self.state} @ {self.cursor:%Y-%m-%d}'
```

Generate the migration (do not hand-write field definitions — let Django introspect the model to avoid drift):

```bash
docker compose run --rm web python manage.py makemigrations monitors --name entrybackfilljob
```

Confirm the generated file is `camp/apps/monitors/migrations/0037_entrybackfilljob.py` (next available number per the existing sequence). If Django names it differently, rename it to match this plan's file list.

Add to `camp/apps/monitors/admin.py`, alongside the existing imports and registrations:

```python
# camp/apps/monitors/admin.py — add to imports
from .models import EntryBackfillJob, Group, Host, LatestEntry, Monitor
```

```python
# camp/apps/monitors/admin.py — new registration
@admin.register(EntryBackfillJob)
class EntryBackfillJobAdmin(admin.ModelAdmin):
    list_display = [
        'state', 'cursor', 'range_start', 'range_end',
        'pending_tasks', 'raw_entries_created', 'consecutive_failures', 'modified',
    ]
    list_filter = ['state']
    ordering = ['-created']
    readonly_fields = [
        f.name for f in EntryBackfillJob._meta.get_fields()
        if isinstance(f, models.Field) and f.name != 'state'
    ]
```

- [ ] **Step 4: Run migration and test to verify they pass**

Run: `docker compose run --rm web python manage.py migrate monitors`
Run: `docker compose run --rm test pytest camp/apps/monitors/test_legacy_backfill.py::EntryBackfillJobTests -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add camp/apps/monitors/models.py camp/apps/monitors/migrations/0037_entrybackfilljob.py \
  camp/apps/monitors/admin.py camp/apps/monitors/test_legacy_backfill.py
git commit -m "feat(monitors): add EntryBackfillJob model, migration, and admin"
```

---

### Task 4: `backfill_monitor_chunk` task

**Files:**
- Modify: `camp/apps/monitors/tasks.py`
- Test: `camp/apps/monitors/test_legacy_backfill.py`

**Interfaces:**
- Consumes: `LEGACY_BACKFILL_MAP`, `find_missing_raw_entries` (Tasks 1–2), `EntryBackfillJob` (Task 3).
- Produces: `backfill_monitor_chunk(job_id, monitor_id, chunk_start, chunk_end, batch_id)` — a `db_task` on the `secondary` queue.

- [ ] **Step 1: Write the failing test**

```python
# append to camp/apps/monitors/test_legacy_backfill.py
from camp.apps.monitors.tasks import backfill_monitor_chunk


class BackfillMonitorChunkTaskTests(TestCase):
    fixtures = ['purple-air.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.first()
        self.chunk_start = _ts(2023, 1, 1)
        self.chunk_end = _ts(2023, 1, 8)
        self.job = EntryBackfillJob.objects.create(
            cursor=self.chunk_end, range_start=_ts(2020, 1, 1), range_end=self.chunk_end,
            chunk_start=self.chunk_start, pending_tasks=1, batch_id=1,
        )
        Entry.objects.create(
            monitor=self.monitor, sensor='a', timestamp=self.chunk_start + timedelta(hours=1),
            location=self.monitor.location, pm25_reported=Decimal('5.0'),
        )

    def test_creates_raw_entries_and_decrements_pending_tasks(self):
        backfill_monitor_chunk(self.job.pk, str(self.monitor.pk), self.chunk_start, self.chunk_end, 1)
        assert entry_models.PM25.objects.filter(monitor=self.monitor, stage=entry_models.PM25.Stage.RAW).exists()
        self.job.refresh_from_db()
        assert self.job.pending_tasks == 0
        assert self.job.raw_entries_created == 1

    def test_stale_batch_id_still_creates_entries_but_does_not_decrement(self):
        backfill_monitor_chunk(self.job.pk, str(self.monitor.pk), self.chunk_start, self.chunk_end, 999)
        assert entry_models.PM25.objects.filter(monitor=self.monitor, stage=entry_models.PM25.Stage.RAW).exists()
        self.job.refresh_from_db()
        assert self.job.pending_tasks == 1

    def test_idempotent_rerun_does_not_duplicate(self):
        backfill_monitor_chunk(self.job.pk, str(self.monitor.pk), self.chunk_start, self.chunk_end, 1)
        self.job.batch_id = 2
        self.job.pending_tasks = 1
        self.job.save()
        backfill_monitor_chunk(self.job.pk, str(self.monitor.pk), self.chunk_start, self.chunk_end, 2)
        assert entry_models.PM25.objects.filter(monitor=self.monitor, stage=entry_models.PM25.Stage.RAW).count() == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose run --rm test pytest camp/apps/monitors/test_legacy_backfill.py::BackfillMonitorChunkTaskTests -v`
Expected: FAIL with `ImportError: cannot import name 'backfill_monitor_chunk'`

- [ ] **Step 3: Write the implementation**

```python
# camp/apps/monitors/tasks.py — add to imports
from django.db.models import F

from camp.apps.monitors.legacy_backfill import (
    LEGACY_BACKFILL_MAP, find_missing_raw_entries,
)
```

```python
# camp/apps/monitors/tasks.py — new task
@db_task(priority=1, queue='secondary')
def backfill_monitor_chunk(job_id, monitor_id, chunk_start, chunk_end, batch_id):
    '''
    For one monitor, insert any RAW entries missing in [chunk_start, chunk_end)
    across its LEGACY_BACKFILL_MAP-configured entry types, then report completion.
    '''
    monitor = _resolve_monitor_subclass(monitor_id)

    created_count = 0
    for entry_model, mapping in LEGACY_BACKFILL_MAP.get(type(monitor), {}).items():
        missing = find_missing_raw_entries(monitor, entry_model, mapping, chunk_start, chunk_end)
        if missing:
            entry_model.objects.bulk_create(
                missing,
                update_conflicts=True,
                unique_fields=['monitor', 'timestamp', 'sensor', 'stage', 'processor'],
                update_fields=[f.name for f in entry_model.declared_fields],
            )
            created_count += len(missing)

    EntryBackfillJob.objects.filter(
        pk=job_id, batch_id=batch_id,
    ).update(
        pending_tasks=F('pending_tasks') - 1,
        raw_entries_created=F('raw_entries_created') + created_count,
    )


def _resolve_monitor_subclass(monitor_id):
    '''
    Monitor is base-table multi-table inheritance; find which of the
    LEGACY_BACKFILL_MAP-eligible concrete subclasses this id belongs to.
    '''
    from camp.apps.monitors.legacy_backfill import eligible_monitor_classes

    for monitor_cls in eligible_monitor_classes():
        monitor = monitor_cls.objects.filter(pk=monitor_id).first()
        if monitor is not None:
            return monitor
    raise Monitor.DoesNotExist(f'No eligible monitor subclass found for id={monitor_id}')
```

Also add `EntryBackfillJob` to the existing model import line at the top of `camp/apps/monitors/tasks.py`:

```python
from .models import Entry, EntryBackfillJob, Monitor
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose run --rm test pytest camp/apps/monitors/test_legacy_backfill.py::BackfillMonitorChunkTaskTests -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add camp/apps/monitors/tasks.py camp/apps/monitors/test_legacy_backfill.py
git commit -m "feat(monitors): add backfill_monitor_chunk task"
```

---

### Task 5: `backfill_legacy_entries_tick` orchestrator

**Files:**
- Modify: `camp/apps/monitors/tasks.py`
- Test: `camp/apps/monitors/test_legacy_backfill.py`

**Interfaces:**
- Consumes: `EntryBackfillJob` (Task 3), `backfill_monitor_chunk` (Task 4), `chunk_start_for`/`monitors_with_legacy_data_in` (Task 2).
- Produces: `backfill_legacy_entries_tick()` — a `db_periodic_task` on the `primary` queue, plus helpers `_entry_backfill_dispatch_chunk`, `_entry_backfill_complete_chunk`, `_entry_backfill_restart_batch` (module-private, tested via the tick function and direct calls).

- [ ] **Step 1: Write the failing tests**

```python
# append to camp/apps/monitors/test_legacy_backfill.py
from django.db import transaction
from django.test import TransactionTestCase

from camp.apps.monitors.tasks import backfill_legacy_entries_tick


class BackfillLegacyEntriesTickDispatchTests(TestCase):
    fixtures = ['purple-air.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.first()
        self.range_start = _ts(2020, 1, 1)
        self.range_end = _ts(2023, 1, 8)
        Entry.objects.create(
            monitor=self.monitor, sensor='a', timestamp=self.range_end - timedelta(hours=1),
            location=self.monitor.location, pm25_reported=Decimal('5.0'),
        )
        self.job = EntryBackfillJob.objects.create(
            cursor=self.range_end, range_start=self.range_start, range_end=self.range_end, chunk_days=7,
        )

    def test_dispatches_a_chunk_and_creates_entries_synchronously(self):
        # Huey runs in immediate mode under camp.settings.test, so the fanned-out
        # backfill_monitor_chunk call executes inline within this tick call.
        backfill_legacy_entries_tick()
        self.job.refresh_from_db()
        assert self.job.pending_tasks == 0  # drained immediately (immediate-mode Huey)
        assert entry_models.PM25.objects.filter(monitor=self.monitor, stage=entry_models.PM25.Stage.RAW).exists()

    def test_no_op_when_no_running_job(self):
        self.job.state = EntryBackfillJob.State.DONE
        self.job.save()
        backfill_legacy_entries_tick()  # should not raise

    def test_advances_cursor_and_marks_done_when_range_exhausted(self):
        self.job.range_start = self.range_end - timedelta(days=1)
        self.job.cursor = self.range_end
        self.job.chunk_days = 7
        self.job.save()
        backfill_legacy_entries_tick()
        # First tick dispatches the (single, clamped) chunk and drains it immediately.
        backfill_legacy_entries_tick()
        self.job.refresh_from_db()
        assert self.job.state == EntryBackfillJob.State.DONE
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose run --rm test pytest camp/apps/monitors/test_legacy_backfill.py::BackfillLegacyEntriesTickDispatchTests -v`
Expected: FAIL with `ImportError: cannot import name 'backfill_legacy_entries_tick'`

- [ ] **Step 3: Write the implementation**

`camp/apps/monitors/tasks.py` already imports `timedelta` and `timezone` at the top of
the file — no change needed there. Add the following new imports:

```python
# camp/apps/monitors/tasks.py — add to imports
from django.db import transaction
from django.db.models import Q

from camp.apps.monitors.legacy_backfill import chunk_start_for, monitors_with_legacy_data_in
```

```python
# camp/apps/monitors/tasks.py — new orchestrator
ENTRY_BACKFILL_LOCK_STALE_SECONDS = 30
ENTRY_BACKFILL_BATCH_STALE_MINUTES = 60
ENTRY_BACKFILL_MAX_CONSECUTIVE_FAILURES = 5


@db_periodic_task(crontab(minute='*'), priority=1, queue='primary')
def backfill_legacy_entries_tick():
    '''
    Drive one step of the active EntryBackfillJob, if any. Never blocks on the
    sub-tasks it dispatches. See
    docs/superpowers/specs/2026-07-28-legacy-entries-backfill-design.md.
    '''
    now = timezone.now()

    with transaction.atomic():
        job = (
            EntryBackfillJob.objects
            .select_for_update(skip_locked=True)
            .filter(state=EntryBackfillJob.State.RUNNING)
            .filter(
                Q(locked_at__isnull=True) |
                Q(locked_at__lt=now - timedelta(seconds=ENTRY_BACKFILL_LOCK_STALE_SECONDS))
            )
            .order_by('created')
            .first()
        )
        if job is None:
            return

        job.locked_at = now
        job.save(update_fields=['locked_at'])

        if job.pending_tasks > 0:
            stale_before = now - timedelta(minutes=ENTRY_BACKFILL_BATCH_STALE_MINUTES)
            if job.phase_started_at and job.phase_started_at < stale_before:
                _entry_backfill_restart_batch(job)
            return

        if job.chunk_start is not None:
            _entry_backfill_complete_chunk(job)
        else:
            _entry_backfill_dispatch_chunk(job)


def _entry_backfill_dispatch_chunk(job):
    chunk_start = chunk_start_for(job.cursor, job.range_start, job.chunk_days)
    monitor_ids = monitors_with_legacy_data_in(chunk_start, job.cursor)

    job.chunk_start = chunk_start
    job.batch_id += 1
    job.pending_tasks = len(monitor_ids)
    job.phase_started_at = timezone.now()
    job.save()

    job_id = job.pk
    batch_id = job.batch_id
    chunk_end = job.cursor
    for monitor_id in monitor_ids:
        transaction.on_commit(
            lambda m=monitor_id: backfill_monitor_chunk(job_id, str(m), chunk_start, chunk_end, batch_id)
        )


def _entry_backfill_complete_chunk(job):
    job.cursor = job.chunk_start
    job.chunk_start = None
    job.pending_tasks = 0
    job.consecutive_failures = 0
    job.last_error = ''
    if job.cursor <= job.range_start:
        job.state = EntryBackfillJob.State.DONE
    job.save()


def _entry_backfill_restart_batch(job):
    job.consecutive_failures += 1
    job.last_error = (
        f'Batch {job.batch_id} stalled with {job.pending_tasks} pending task(s); restarting.'
    )

    if job.consecutive_failures >= ENTRY_BACKFILL_MAX_CONSECUTIVE_FAILURES:
        job.pending_tasks = 0
        job.state = EntryBackfillJob.State.FAILED
        job.save()
        return

    chunk_start = job.chunk_start
    monitor_ids = monitors_with_legacy_data_in(chunk_start, job.cursor)

    job.batch_id += 1
    job.pending_tasks = len(monitor_ids)
    job.phase_started_at = timezone.now()
    job.save()

    job_id = job.pk
    batch_id = job.batch_id
    chunk_end = job.cursor
    for monitor_id in monitor_ids:
        transaction.on_commit(
            lambda m=monitor_id: backfill_monitor_chunk(job_id, str(m), chunk_start, chunk_end, batch_id)
        )
```

Note: because `chunk_start_for` clamps to `range_start`, and a monitor-less chunk still fully drains on dispatch (0 tasks → `pending_tasks == 0` immediately), the "done" test above requires exactly two ticks: one to dispatch the single clamped chunk (which, since Huey runs in immediate mode in tests, actually finishes the dispatched task synchronously too — but `pending_tasks` is only decremented by the *task*, and the dispatch itself doesn't decrement it, so a second tick is still needed to observe `chunk_start is not None and pending_tasks == 0` and finalize). This mirrors the summaries backfill's tick cadence exactly.

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose run --rm test pytest camp/apps/monitors/test_legacy_backfill.py::BackfillLegacyEntriesTickDispatchTests -v`
Expected: PASS. If `test_advances_cursor_and_marks_done_when_range_exhausted` fails because it needs a third tick (e.g. if the dispatched chunk has monitors and immediate-mode execution completes the task but the tick that dispatched it doesn't also complete the chunk in the same call), add one more `backfill_legacy_entries_tick()` call to that test and re-run — immediate-mode Huey still requires a separate tick invocation to notice `pending_tasks` has reached zero, since the decrement happens inside the task call, not the dispatch call.

- [ ] **Step 5: Commit**

```bash
git add camp/apps/monitors/tasks.py camp/apps/monitors/test_legacy_backfill.py
git commit -m "feat(monitors): add backfill_legacy_entries_tick orchestrator"
```

---

### Task 6: `backfill_legacy_entries` management command

**Files:**
- Create: `camp/apps/monitors/management/commands/backfill_legacy_entries.py`
- Test: `camp/apps/monitors/test_legacy_backfill.py`

**Interfaces:**
- Consumes: `EntryBackfillJob` (Task 3).
- Produces: `manage.py backfill_legacy_entries {start,status,cancel}`.

- [ ] **Step 1: Write the failing tests**

```python
# append to camp/apps/monitors/test_legacy_backfill.py
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError


class BackfillLegacyEntriesCommandTests(TestCase):
    def test_start_creates_job(self):
        out = StringIO()
        call_command('backfill_legacy_entries', 'start', '--from', '2020-01-01', stdout=out)
        assert EntryBackfillJob.objects.filter(state=EntryBackfillJob.State.RUNNING).exists()
        assert 'Started' in out.getvalue()

    def test_start_refuses_second_job_without_force(self):
        call_command('backfill_legacy_entries', 'start', '--from', '2020-01-01')
        try:
            call_command('backfill_legacy_entries', 'start', '--from', '2020-01-01')
            assert False, 'expected CommandError'
        except CommandError:
            pass
        assert EntryBackfillJob.objects.count() == 1

    def test_start_with_force_replaces_job(self):
        call_command('backfill_legacy_entries', 'start', '--from', '2020-01-01')
        call_command('backfill_legacy_entries', 'start', '--from', '2021-01-01', '--force')
        assert EntryBackfillJob.objects.count() == 1
        job = EntryBackfillJob.objects.first()
        assert job.range_start.year == 2021

    def test_status_with_no_job(self):
        out = StringIO()
        call_command('backfill_legacy_entries', 'status', stdout=out)
        assert 'No backfill job' in out.getvalue()

    def test_status_with_job(self):
        call_command('backfill_legacy_entries', 'start', '--from', '2020-01-01')
        out = StringIO()
        call_command('backfill_legacy_entries', 'status', stdout=out)
        assert 'running' in out.getvalue()

    def test_cancel_sets_state_done(self):
        call_command('backfill_legacy_entries', 'start', '--from', '2020-01-01')
        call_command('backfill_legacy_entries', 'cancel')
        job = EntryBackfillJob.objects.first()
        assert job.state == EntryBackfillJob.State.DONE
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose run --rm test pytest camp/apps/monitors/test_legacy_backfill.py::BackfillLegacyEntriesCommandTests -v`
Expected: FAIL with a "no such management command" error.

- [ ] **Step 3: Write the implementation**

```python
# camp/apps/monitors/management/commands/backfill_legacy_entries.py
from datetime import datetime

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.utils.dateparse import parse_date

from camp.utils.datetime import make_aware
from camp.apps.monitors.models import EntryBackfillJob


class Command(BaseCommand):
    help = 'Start, monitor, or cancel the legacy Entry -> entries RAW-stage backfill job.'

    def add_arguments(self, parser):
        parser.add_argument('action', choices=['start', 'status', 'cancel'])
        parser.add_argument('--from', dest='date_from', metavar='YYYY-MM-DD',
            help='Earliest date to backfill (required for start)')
        parser.add_argument('--to', dest='date_to', metavar='YYYY-MM-DD',
            help='Latest date to backfill, exclusive (default: now)')
        parser.add_argument('--force', action='store_true',
            help='Replace an existing running/paused job instead of refusing to start a new one')
        parser.add_argument('--chunk-days', dest='chunk_days', type=int, default=7,
            help='Days per chunk (default: 7)')

    def handle(self, *args, **options):
        action = options['action']
        if action == 'start':
            self._start(options)
        elif action == 'status':
            self._status()
        elif action == 'cancel':
            self._cancel()

    def _start(self, options):
        if not options['date_from']:
            raise CommandError('--from is required for start')

        chunk_days = options['chunk_days']
        if chunk_days < 1:
            raise CommandError('--chunk-days must be at least 1')

        active = EntryBackfillJob.objects.filter(
            state__in=[EntryBackfillJob.State.RUNNING, EntryBackfillJob.State.PAUSED],
        ).first()
        if active and not options['force']:
            raise CommandError(
                f'A backfill job is already {active.state} (cursor {active.cursor:%Y-%m-%d}). '
                'Pass --force to replace it.'
            )
        if active and options['force']:
            active.delete()

        range_start = self._parse_date(options['date_from'])
        range_end = (
            self._parse_date(options['date_to'])
            if options['date_to']
            else timezone.now()
        )
        if range_start >= range_end:
            raise CommandError('--from must be before --to')

        EntryBackfillJob.objects.create(
            cursor=range_end,
            range_start=range_start,
            range_end=range_end,
            chunk_days=chunk_days,
        )
        self.stdout.write(self.style.SUCCESS(
            f'Started backfill job: {range_start:%Y-%m-%d} -> {range_end:%Y-%m-%d} '
            f'({chunk_days}-day chunks)'
        ))

    def _status(self):
        job = EntryBackfillJob.objects.order_by('-created').first()
        if job is None:
            self.stdout.write('No backfill job has been started.')
            return

        total_seconds = (job.range_end - job.range_start).total_seconds()
        done_seconds = (job.range_end - job.cursor).total_seconds()
        percent = 100 * done_seconds / total_seconds if total_seconds else 100

        self.stdout.write(f'State: {job.state}')
        self.stdout.write(f'Cursor: {job.cursor:%Y-%m-%d}')
        self.stdout.write(f'Range: {job.range_start:%Y-%m-%d} -> {job.range_end:%Y-%m-%d}')
        self.stdout.write(f'Chunk size: {job.chunk_days} day(s)')
        self.stdout.write(f'Progress: {percent:.1f}%')
        self.stdout.write(f'RAW entries created: {job.raw_entries_created}')
        if job.last_error:
            self.stdout.write(self.style.WARNING(f'Last error: {job.last_error}'))

    def _cancel(self):
        job = EntryBackfillJob.objects.filter(
            state__in=[EntryBackfillJob.State.RUNNING, EntryBackfillJob.State.PAUSED],
        ).first()
        if job is None:
            self.stdout.write('No active backfill job to cancel.')
            return
        job.state = EntryBackfillJob.State.DONE
        job.save(update_fields=['state'])
        self.stdout.write(self.style.SUCCESS('Backfill job cancelled.'))

    def _parse_date(self, value):
        d = parse_date(value)
        if d is None:
            raise CommandError(f'Invalid date: {value!r}. Use YYYY-MM-DD.')
        return make_aware(datetime(d.year, d.month, d.day), settings.DEFAULT_TIMEZONE)
```

Create the required empty `__init__.py` files if they don't already exist (they should, since other management commands already live under `camp/apps/monitors/management/commands/`):

```bash
ls camp/apps/monitors/management/commands/__init__.py
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose run --rm test pytest camp/apps/monitors/test_legacy_backfill.py::BackfillLegacyEntriesCommandTests -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add camp/apps/monitors/management/commands/backfill_legacy_entries.py camp/apps/monitors/test_legacy_backfill.py
git commit -m "feat(monitors): add backfill_legacy_entries management command"
```

---

### Task 7: Retire `Monitor.get_entry_migration_status()`

**Files:**
- Modify: `camp/apps/monitors/models.py`

**Interfaces:**
- Consumes: nothing (removal only).
- Produces: nothing new — this task deletes dead code superseded by Tasks 1–6.

- [ ] **Step 1: Confirm it's unused elsewhere**

```bash
grep -rn "get_entry_migration_status" camp/
```

Expected: only the method definition itself in `camp/apps/monitors/models.py` (no callers, no tests reference it — already confirmed during the design phase). If any callers turn up, stop and re-scope this task rather than deleting code still in use.

- [ ] **Step 2: Delete the method**

Remove the entire `get_entry_migration_status` method from `camp/apps/monitors/models.py` (currently sits between `check_latest` and the `LCSMixin` class definition).

- [ ] **Step 3: Run the monitors test suite to confirm nothing broke**

Run: `docker compose run --rm test pytest camp/apps/monitors/tests.py -v`
Expected: PASS, no failures related to the removed method.

- [ ] **Step 4: Commit**

```bash
git add camp/apps/monitors/models.py
git commit -m "refactor(monitors): remove get_entry_migration_status, superseded by EntryBackfillJob"
```

---

### Task 8: Pipeline idempotency fix

**Files:**
- Modify: `camp/apps/calibrations/core/processors/base.py`
- Test: check whether `camp/apps/calibrations/core/processors/` or `camp/apps/calibrations/tests.py` already has processor-level tests before creating a new file — if a suitable existing test module covers `BaseProcessor`, add to it; otherwise create `camp/apps/calibrations/core/processors/test_base.py`.

**Interfaces:**
- Consumes: `BaseEntry.validation_check()` (`camp/apps/entries/models.py:182-193`, existing).
- Produces: `BaseProcessor.run()` returns the existing matching entry instead of `None` when one is already present.

- [ ] **Step 1: Check for an existing test location**

```bash
find camp/apps/calibrations -iname "*test*"
```

Use whatever file already exists for processor-level tests if one covers this area; otherwise create `camp/apps/calibrations/core/processors/test_base.py`.

- [ ] **Step 2: Write the failing test**

```python
# camp/apps/calibrations/core/processors/test_base.py (or appended to the existing test file found above)
from decimal import Decimal

from django.test import TestCase

from camp.apps.calibrations.core.processors.base import BaseProcessor
from camp.apps.entries import models as entry_models
from camp.apps.monitors.purpleair.models import PurpleAir


class _AlwaysDuplicateProcessor(BaseProcessor):
    '''Minimal stand-in processor: process() returns a clone that will always
    collide with an existing entry, to exercise the "already exists" path of
    BaseProcessor.run() without depending on a specific real processor's math.
    '''
    entry_model = entry_models.PM25
    required_stage = entry_models.PM25.Stage.RAW
    next_stage = entry_models.PM25.Stage.CORRECTED
    required_context = []

    def process(self):
        return self.build_entry(value=self.entry.value)


class BaseProcessorRunIdempotencyTests(TestCase):
    fixtures = ['purple-air.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.first()
        self.raw = entry_models.PM25.objects.create(
            monitor=self.monitor, sensor='a', timestamp='2023-01-01T00:00:00Z',
            location=self.monitor.location, stage=entry_models.PM25.Stage.RAW,
            processor='', value=Decimal('10.00'),
        )
        self.existing_corrected = entry_models.PM25.objects.create(
            monitor=self.monitor, sensor='a', timestamp=self.raw.timestamp,
            location=self.monitor.location, stage=entry_models.PM25.Stage.CORRECTED,
            processor='_AlwaysDuplicateProcessor', value=Decimal('10.00'), origin=self.raw,
        )

    def test_run_returns_existing_entry_instead_of_none(self):
        processor = _AlwaysDuplicateProcessor(self.raw)
        result = processor.run()
        assert result is not None
        assert result.pk == self.existing_corrected.pk

    def test_run_does_not_create_a_duplicate(self):
        processor = _AlwaysDuplicateProcessor(self.raw)
        processor.run()
        count = entry_models.PM25.objects.filter(
            monitor=self.monitor, timestamp=self.raw.timestamp,
            sensor='a', stage=entry_models.PM25.Stage.CORRECTED,
        ).count()
        assert count == 1

    def test_run_still_creates_when_nothing_exists(self):
        self.existing_corrected.delete()
        processor = _AlwaysDuplicateProcessor(self.raw)
        result = processor.run()
        assert result is not None
        assert result.pk is not None
        assert entry_models.PM25.objects.filter(
            monitor=self.monitor, timestamp=self.raw.timestamp,
            sensor='a', stage=entry_models.PM25.Stage.CORRECTED,
        ).count() == 1
```

- [ ] **Step 3: Run test to verify it fails**

Run: `docker compose run --rm test pytest camp/apps/calibrations/core/processors/test_base.py -v`
Expected: FAIL on `test_run_returns_existing_entry_instead_of_none` — current `run()` returns `None` (`processed.validation_check()` is `False`, so the `if` body never executes and the function falls through to implicit `None`).

- [ ] **Step 4: Write the implementation**

```python
# camp/apps/calibrations/core/processors/base.py — replace run()
    def run(self, commit=True):
        '''
        Runs the processor and returns the new (or already-existing) entry,
        or None if no value is produced. If a matching entry already exists
        (same monitor/timestamp/sensor/stage/processor), returns that entry
        instead of creating a duplicate or silently stopping the pipeline —
        this is what lets process_entry_pipeline safely resume a partially
        processed chain on re-run.
        '''
        if not self.is_valid():
            return

        processed = self.process()
        if processed is None:
            return

        if processed.validation_check():
            if commit:
                processed.save()
            return processed

        return processed.__class__.objects.filter(
            monitor_id=processed.monitor_id,
            timestamp=processed.timestamp,
            sensor=processed.sensor,
            stage=processed.stage,
            processor=processed.processor,
        ).first()
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `docker compose run --rm test pytest camp/apps/calibrations/core/processors/test_base.py -v`
Expected: PASS

- [ ] **Step 6: Run the full calibrations and monitors test suites to catch regressions**

Run: `docker compose run --rm test pytest camp/apps/calibrations/ camp/apps/monitors/ -v`
Expected: PASS. This fix changes the return value of `run()` in the "already exists" branch from `None` to an entry — check for any code that relied on `run()`'s truthiness specifically meaning "freshly created" (e.g. anything conditionally sending an alert or notification only when `run()` returns non-None). If found, note it but do not change that code as part of this task — flag it in the task's commit message and report it back for a follow-up decision, since changing alert-firing behavior is out of scope for this plan.

- [ ] **Step 7: Commit**

```bash
git add camp/apps/calibrations/core/processors/base.py camp/apps/calibrations/core/processors/test_base.py
git commit -m "fix(calibrations): BaseProcessor.run() returns existing entry instead of None, unblocking pipeline resume"
```

---

### Task 9: Pipeline gap-detection helpers (pipeline phase)

**Files:**
- Modify: `camp/apps/monitors/legacy_backfill.py`
- Test: `camp/apps/monitors/test_legacy_backfill.py`

**Interfaces:**
- Consumes: `LEGACY_BACKFILL_MAP`, `eligible_monitor_classes` (Tasks 1–2).
- Produces: `pipeline_entry_models(monitor_class) -> dict[EntryModel, terminal_stage]`, `find_incomplete_pipelines(monitor, entry_model, terminal_stage, chunk_start, chunk_end) -> list[EntryModel instance]`, `monitors_with_incomplete_pipelines_in(chunk_start, chunk_end) -> list[monitor_id]`.

- [ ] **Step 1: Write the failing tests**

```python
# append to camp/apps/monitors/test_legacy_backfill.py
from camp.apps.monitors.legacy_backfill import (
    find_incomplete_pipelines, monitors_with_incomplete_pipelines_in, pipeline_entry_models,
)


class PipelineEntryModelsTests(TestCase):
    def test_purpleair_pm25_has_calibrated_terminal_stage(self):
        models_map = pipeline_entry_models(PurpleAir)
        assert models_map[entry_models.PM25] == entry_models.PM25.Stage.CALIBRATED

    def test_purpleair_pm10_excluded_no_processors(self):
        models_map = pipeline_entry_models(PurpleAir)
        assert entry_models.PM10 not in models_map

    def test_airnow_pm25_has_cleaned_terminal_stage(self):
        models_map = pipeline_entry_models(AirNow)
        assert models_map[entry_models.PM25] == entry_models.PM25.Stage.CLEANED


class FindIncompletePipelinesTests(TestCase):
    fixtures = ['purple-air.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.first()
        self.ts = _ts(2023, 1, 1)

    def test_finds_raw_entry_with_no_terminal_stage_entry(self):
        raw = entry_models.PM25.objects.create(
            monitor=self.monitor, sensor='a', timestamp=self.ts, location=self.monitor.location,
            stage=entry_models.PM25.Stage.RAW, processor='', value=Decimal('5.0'),
        )
        incomplete = find_incomplete_pipelines(
            self.monitor, entry_models.PM25, entry_models.PM25.Stage.CALIBRATED,
            self.ts, self.ts + timedelta(hours=1),
        )
        assert [e.pk for e in incomplete] == [raw.pk]

    def test_skips_raw_entry_that_already_has_terminal_stage_entry(self):
        raw = entry_models.PM25.objects.create(
            monitor=self.monitor, sensor='a', timestamp=self.ts, location=self.monitor.location,
            stage=entry_models.PM25.Stage.RAW, processor='', value=Decimal('5.0'),
        )
        entry_models.PM25.objects.create(
            monitor=self.monitor, sensor='a', timestamp=self.ts, location=self.monitor.location,
            stage=entry_models.PM25.Stage.CALIBRATED, processor='SomeCalibrator', value=Decimal('5.0'),
            origin=raw,
        )
        incomplete = find_incomplete_pipelines(
            self.monitor, entry_models.PM25, entry_models.PM25.Stage.CALIBRATED,
            self.ts, self.ts + timedelta(hours=1),
        )
        assert incomplete == []

    def test_finds_raw_entry_stuck_at_intermediate_stage(self):
        # Left over from a previous partial migration: RAW and CORRECTED exist,
        # but CLEANED/CALIBRATED never ran.
        raw = entry_models.PM25.objects.create(
            monitor=self.monitor, sensor='a', timestamp=self.ts, location=self.monitor.location,
            stage=entry_models.PM25.Stage.RAW, processor='', value=Decimal('5.0'),
        )
        entry_models.PM25.objects.create(
            monitor=self.monitor, sensor='a', timestamp=self.ts, location=self.monitor.location,
            stage=entry_models.PM25.Stage.CORRECTED, processor='PM25_LCS_Correction',
            value=Decimal('5.0'), origin=raw,
        )
        incomplete = find_incomplete_pipelines(
            self.monitor, entry_models.PM25, entry_models.PM25.Stage.CALIBRATED,
            self.ts, self.ts + timedelta(hours=1),
        )
        assert [e.pk for e in incomplete] == [raw.pk]


class MonitorsWithIncompletePipelinesInTests(TestCase):
    fixtures = ['purple-air.yaml']

    def test_finds_monitor_with_incomplete_pipeline(self):
        monitor = PurpleAir.objects.first()
        ts = _ts(2023, 1, 1)
        entry_models.PM25.objects.create(
            monitor=monitor, sensor='a', timestamp=ts, location=monitor.location,
            stage=entry_models.PM25.Stage.RAW, processor='', value=Decimal('5.0'),
        )
        ids = monitors_with_incomplete_pipelines_in(ts, ts + timedelta(hours=1))
        assert monitor.pk in ids

    def test_excludes_fully_processed_monitor(self):
        monitor = PurpleAir.objects.first()
        ts = _ts(2023, 1, 1)
        raw = entry_models.PM25.objects.create(
            monitor=monitor, sensor='a', timestamp=ts, location=monitor.location,
            stage=entry_models.PM25.Stage.RAW, processor='', value=Decimal('5.0'),
        )
        entry_models.PM25.objects.create(
            monitor=monitor, sensor='a', timestamp=ts, location=monitor.location,
            stage=entry_models.PM25.Stage.CALIBRATED, processor='SomeCalibrator',
            value=Decimal('5.0'), origin=raw,
        )
        ids = monitors_with_incomplete_pipelines_in(ts, ts + timedelta(hours=1))
        assert monitor.pk not in ids
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose run --rm test pytest camp/apps/monitors/test_legacy_backfill.py -k Pipeline -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Write the implementation**

```python
# append to camp/apps/monitors/legacy_backfill.py

def pipeline_entry_models(monitor_class):
    '''
    EntryModels this monitor type both backfills from legacy data and runs
    through a processing pipeline (declares 'processors' in ENTRY_CONFIG),
    mapped to their terminal (final configured) stage.
    '''
    result = {}
    mapping = LEGACY_BACKFILL_MAP.get(monitor_class, {})
    for entry_model in mapping:
        config = monitor_class.ENTRY_CONFIG.get(entry_model, {})
        if 'processors' in config:
            result[entry_model] = config['allowed_stages'][-1]
    return result


def find_incomplete_pipelines(monitor, entry_model, terminal_stage, chunk_start, chunk_end):
    '''
    Returns RAW-stage entry_model instances in the window that have no
    corresponding terminal-stage entry yet (any processor). Safe to call
    repeatedly.
    '''
    raw_qs = entry_model.objects.filter(
        monitor=monitor,
        stage=entry_model.Stage.RAW,
        timestamp__gte=chunk_start,
        timestamp__lt=chunk_end,
    )

    complete_keys = set(
        entry_model.objects.filter(
            monitor=monitor,
            stage=terminal_stage,
            timestamp__gte=chunk_start,
            timestamp__lt=chunk_end,
        ).values_list('timestamp', 'sensor')
    )

    return [
        entry for entry in raw_qs
        if (entry.timestamp, entry.sensor) not in complete_keys
    ]


def monitors_with_incomplete_pipelines_in(chunk_start, chunk_end):
    '''
    Returns pks of monitors (of the eligible types) with at least one RAW
    entry in [chunk_start, chunk_end) missing its terminal-stage counterpart,
    across any of that monitor type's pipeline-eligible entry models.
    '''
    monitor_ids = set()
    for monitor_cls in eligible_monitor_classes():
        models_map = pipeline_entry_models(monitor_cls)
        if not models_map:
            continue

        for entry_model, terminal_stage in models_map.items():
            raw_in_range = entry_model.objects.filter(
                monitor=OuterRef('pk'),
                stage=entry_model.Stage.RAW,
                timestamp__gte=chunk_start,
                timestamp__lt=chunk_end,
            )
            terminal_in_range = entry_model.objects.filter(
                monitor=OuterRef('pk'),
                stage=terminal_stage,
                timestamp__gte=chunk_start,
                timestamp__lt=chunk_end,
            )
            ids = (monitor_cls.objects
                .annotate(has_raw=Exists(raw_in_range))
                .filter(has_raw=True)
                .values_list('pk', flat=True))
            # Cheap pre-filter above (has any RAW at all in window); the precise
            # "missing terminal counterpart" check happens per-monitor in
            # find_incomplete_pipelines when the chunk task actually runs, since
            # comparing per-entry keys isn't expressible as a single annotation
            # without risking false negatives on the sensor-collapse cases.
            monitor_ids.update(ids)

    return list(monitor_ids)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose run --rm test pytest camp/apps/monitors/test_legacy_backfill.py -k Pipeline -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add camp/apps/monitors/legacy_backfill.py camp/apps/monitors/test_legacy_backfill.py
git commit -m "feat(monitors): add pipeline gap-detection helpers"
```

---

### Task 10: `PipelineBackfillJob` model, migration, and admin

**Files:**
- Modify: `camp/apps/monitors/models.py`
- Create: `camp/apps/monitors/migrations/0038_pipelinebackfilljob.py`
- Modify: `camp/apps/monitors/admin.py`
- Test: `camp/apps/monitors/test_legacy_backfill.py`

**Interfaces:**
- Produces: `PipelineBackfillJob` model, same shape as `EntryBackfillJob` (Task 3) but with `entries_processed` instead of `raw_entries_created`.

- [ ] **Step 1: Write the failing test**

```python
# append to camp/apps/monitors/test_legacy_backfill.py
from camp.apps.monitors.models import PipelineBackfillJob


class PipelineBackfillJobTests(TestCase):
    def test_defaults(self):
        job = PipelineBackfillJob.objects.create(
            cursor=_ts(2023, 1, 8), range_start=_ts(2020, 1, 1), range_end=_ts(2023, 1, 8),
        )
        assert job.state == PipelineBackfillJob.State.RUNNING
        assert job.chunk_days == 7
        assert job.entries_processed == 0
        assert job.sqid
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose run --rm test pytest camp/apps/monitors/test_legacy_backfill.py::PipelineBackfillJobTests -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Write the model, migration, and admin registration**

```python
# camp/apps/monitors/models.py — new model, alongside EntryBackfillJob
class PipelineBackfillJob(TimeStampedModel):
    '''
    Tracks progress of driving historical RAW entries through the
    correction/cleaning/calibration pipeline. Independent from
    EntryBackfillJob — can run anytime, safe to re-run.
    See docs/superpowers/specs/2026-07-28-legacy-entries-backfill-design.md.
    '''
    class State(models.TextChoices):
        RUNNING = 'running', _('Running')
        PAUSED = 'paused', _('Paused')
        DONE = 'done', _('Done')
        FAILED = 'failed', _('Failed')

    sqid = SqidsField(alphabet=shuffle_alphabet('monitors.PipelineBackfillJob'))

    state = models.CharField(_('state'), max_length=10, choices=State.choices, default=State.RUNNING)

    cursor = models.DateTimeField(_('cursor'))
    chunk_start = models.DateTimeField(_('chunk start'), null=True, blank=True)
    chunk_days = models.PositiveSmallIntegerField(_('chunk days'), default=7)
    range_start = models.DateTimeField(_('range start'))
    range_end = models.DateTimeField(_('range end'))

    pending_tasks = models.PositiveIntegerField(_('pending tasks'), default=0)
    batch_id = models.PositiveIntegerField(_('batch id'), default=0)
    phase_started_at = models.DateTimeField(_('phase started at'), null=True, blank=True)
    locked_at = models.DateTimeField(_('locked at'), null=True, blank=True)

    consecutive_failures = models.PositiveSmallIntegerField(_('consecutive failures'), default=0)
    last_error = models.TextField(_('last error'), blank=True, default='')

    entries_processed = models.PositiveIntegerField(_('entries processed'), default=0)

    def __str__(self):
        return f'{self.state} @ {self.cursor:%Y-%m-%d}'
```

```bash
docker compose run --rm web python manage.py makemigrations monitors --name pipelinebackfilljob
```

Confirm the generated file is `camp/apps/monitors/migrations/0038_pipelinebackfilljob.py`.

```python
# camp/apps/monitors/admin.py — add to imports
from .models import EntryBackfillJob, Group, Host, LatestEntry, Monitor, PipelineBackfillJob
```

```python
# camp/apps/monitors/admin.py — new registration
@admin.register(PipelineBackfillJob)
class PipelineBackfillJobAdmin(admin.ModelAdmin):
    list_display = [
        'state', 'cursor', 'range_start', 'range_end',
        'pending_tasks', 'entries_processed', 'consecutive_failures', 'modified',
    ]
    list_filter = ['state']
    ordering = ['-created']
    readonly_fields = [
        f.name for f in PipelineBackfillJob._meta.get_fields()
        if isinstance(f, models.Field) and f.name != 'state'
    ]
```

- [ ] **Step 4: Run migration and test to verify they pass**

Run: `docker compose run --rm web python manage.py migrate monitors`
Run: `docker compose run --rm test pytest camp/apps/monitors/test_legacy_backfill.py::PipelineBackfillJobTests -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add camp/apps/monitors/models.py camp/apps/monitors/migrations/0038_pipelinebackfilljob.py \
  camp/apps/monitors/admin.py camp/apps/monitors/test_legacy_backfill.py
git commit -m "feat(monitors): add PipelineBackfillJob model, migration, and admin"
```

---

### Task 11: `reprocess_monitor_chunk` task

**Files:**
- Modify: `camp/apps/monitors/tasks.py`
- Test: `camp/apps/monitors/test_legacy_backfill.py`

**Interfaces:**
- Consumes: `pipeline_entry_models`, `find_incomplete_pipelines` (Task 9), `PipelineBackfillJob` (Task 10), the Task 8 idempotency fix.
- Produces: `reprocess_monitor_chunk(job_id, monitor_id, chunk_start, chunk_end, batch_id)` — a `db_task` on the `secondary` queue.

- [ ] **Step 1: Write the failing test**

```python
# append to camp/apps/monitors/test_legacy_backfill.py
from camp.apps.monitors.tasks import reprocess_monitor_chunk


class ReprocessMonitorChunkTaskTests(TestCase):
    fixtures = ['purple-air.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.first()
        self.ts = _ts(2023, 1, 1)
        self.chunk_start = self.ts
        self.chunk_end = self.ts + timedelta(hours=1)
        self.raw = entry_models.PM25.objects.create(
            monitor=self.monitor, sensor='a', timestamp=self.ts, location=self.monitor.location,
            stage=entry_models.PM25.Stage.RAW, processor='', value=Decimal('10.0'),
        )
        self.job = PipelineBackfillJob.objects.create(
            cursor=self.chunk_end, range_start=_ts(2020, 1, 1), range_end=self.chunk_end,
            chunk_start=self.chunk_start, pending_tasks=1, batch_id=1,
        )

    def test_advances_raw_entry_through_pipeline_and_decrements_pending_tasks(self):
        reprocess_monitor_chunk(self.job.pk, str(self.monitor.pk), self.chunk_start, self.chunk_end, 1)
        assert entry_models.PM25.objects.filter(
            monitor=self.monitor, timestamp=self.ts, sensor='a', stage=entry_models.PM25.Stage.CORRECTED,
        ).exists()
        self.job.refresh_from_db()
        assert self.job.pending_tasks == 0
        assert self.job.entries_processed == 1

    def test_stale_batch_id_still_processes_but_does_not_decrement(self):
        reprocess_monitor_chunk(self.job.pk, str(self.monitor.pk), self.chunk_start, self.chunk_end, 999)
        assert entry_models.PM25.objects.filter(
            monitor=self.monitor, timestamp=self.ts, sensor='a', stage=entry_models.PM25.Stage.CORRECTED,
        ).exists()
        self.job.refresh_from_db()
        assert self.job.pending_tasks == 1

    def test_second_sensor_with_no_derived_entries_is_processed_independently(self):
        # PurpleAir dual-sensor: sensor 'b' has its own RAW row; find_incomplete_pipelines
        # (Task 9, revised) selects by derived_entries__isnull=True per RAW row, so both
        # sensors' RAW entries are attempted independently in the same chunk call.
        raw_b = entry_models.PM25.objects.create(
            monitor=self.monitor, sensor='b', timestamp=self.ts, location=self.monitor.location,
            stage=entry_models.PM25.Stage.RAW, processor='', value=Decimal('10.2'),
        )
        reprocess_monitor_chunk(self.job.pk, str(self.monitor.pk), self.chunk_start, self.chunk_end, 1)
        # Sensor 'a' (lexically first) produces the merged CORRECTED entry; sensor 'b'
        # legitimately produces no entry of its own (PM25_LCS_Correction defers to 'a') —
        # both RAW rows were still attempted (entries_processed counts both).
        assert entry_models.PM25.objects.filter(
            monitor=self.monitor, timestamp=self.ts, sensor='', stage=entry_models.PM25.Stage.CORRECTED,
        ).exists()
        self.job.refresh_from_db()
        assert self.job.entries_processed == 2
```

Note: the original brief drafted a `test_resumes_from_partial_chain` case (a RAW entry with an existing CORRECTED-only child, expecting `reprocess_monitor_chunk` to still advance it to CLEANED). That relied on `find_incomplete_pipelines` detecting a stuck-at-intermediate-stage entry — a capability Task 9 deliberately dropped (see Task 9's `derived_entries__isnull=True` redesign and its accepted-limitation test). Do not resurrect that test case here; it now asserts behavior this design intentionally does not provide.

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose run --rm test pytest camp/apps/monitors/test_legacy_backfill.py::ReprocessMonitorChunkTaskTests -v`
Expected: FAIL with `ImportError: cannot import name 'reprocess_monitor_chunk'`.

- [ ] **Step 3: Write the implementation**

```python
# camp/apps/monitors/tasks.py — add to imports
from camp.apps.monitors.legacy_backfill import (
    find_incomplete_pipelines, pipeline_entry_models,
)
```

```python
# camp/apps/monitors/tasks.py — new task
@db_task(priority=1, queue='secondary')
def reprocess_monitor_chunk(job_id, monitor_id, chunk_start, chunk_end, batch_id):
    '''
    For one monitor, drive any RAW entries in [chunk_start, chunk_end) with no
    derived entries yet through process_entry_pipeline, then report completion.
    Safe to re-run (see the BaseProcessor.run() idempotency fix).

    Note: find_incomplete_pipelines (Task 9, revised) selects by
    derived_entries__isnull=True, not by terminal-stage absence — it does not
    catch a RAW entry stuck partway through the pipeline (e.g. CORRECTED
    exists but CLEANED/CALIBRATED doesn't). That's an accepted limitation
    from Task 9's design revision, not something to work around here.
    '''
    monitor = _resolve_monitor_subclass(monitor_id)

    processed_count = 0
    for entry_model, terminal_stage in pipeline_entry_models(type(monitor)).items():
        incomplete = find_incomplete_pipelines(monitor, entry_model, chunk_start, chunk_end)
        for raw_entry in incomplete:
            monitor.process_entry_pipeline(raw_entry, cutoff_stage=terminal_stage)
            processed_count += 1

    PipelineBackfillJob.objects.filter(
        pk=job_id, batch_id=batch_id,
    ).update(
        pending_tasks=F('pending_tasks') - 1,
        entries_processed=F('entries_processed') + processed_count,
    )
```

Note: `find_incomplete_pipelines` takes 4 args now (`monitor, entry_model, chunk_start, chunk_end`) — `terminal_stage` is no longer part of its signature (Task 9 revision), but `pipeline_entry_models` still supplies `terminal_stage` here for the `cutoff_stage` argument to `process_entry_pipeline`.

Add `PipelineBackfillJob` to the model import line at the top of `camp/apps/monitors/tasks.py`:

```python
from .models import Entry, EntryBackfillJob, Monitor, PipelineBackfillJob
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose run --rm test pytest camp/apps/monitors/test_legacy_backfill.py::ReprocessMonitorChunkTaskTests -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add camp/apps/monitors/tasks.py camp/apps/monitors/test_legacy_backfill.py
git commit -m "feat(monitors): add reprocess_monitor_chunk task"
```

---

### Task 12: `reprocess_legacy_pipeline_tick` orchestrator

**Files:**
- Modify: `camp/apps/monitors/tasks.py`
- Test: `camp/apps/monitors/test_legacy_backfill.py`

**Interfaces:**
- Consumes: `PipelineBackfillJob` (Task 10), `reprocess_monitor_chunk` (Task 11), `chunk_start_for`/`monitors_with_incomplete_pipelines_in` (Tasks 2, 9).
- Produces: `reprocess_legacy_pipeline_tick()` — a `db_periodic_task` on the `primary` queue.

- [ ] **Step 1: Write the failing tests**

```python
# append to camp/apps/monitors/test_legacy_backfill.py
from camp.apps.monitors.tasks import reprocess_legacy_pipeline_tick


class ReprocessLegacyPipelineTickTests(TestCase):
    fixtures = ['purple-air.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.first()
        self.range_start = _ts(2020, 1, 1)
        self.range_end = _ts(2023, 1, 8)
        entry_models.PM25.objects.create(
            monitor=self.monitor, sensor='a', timestamp=self.range_end - timedelta(hours=1),
            location=self.monitor.location, stage=entry_models.PM25.Stage.RAW, processor='',
            value=Decimal('10.0'),
        )
        self.job = PipelineBackfillJob.objects.create(
            cursor=self.range_end, range_start=self.range_start, range_end=self.range_end, chunk_days=7,
        )

    def test_dispatches_and_processes_synchronously(self):
        reprocess_legacy_pipeline_tick()
        self.job.refresh_from_db()
        assert self.job.pending_tasks == 0
        assert entry_models.PM25.objects.filter(
            monitor=self.monitor, stage=entry_models.PM25.Stage.CORRECTED,
        ).exists()

    def test_no_op_when_no_running_job(self):
        self.job.state = PipelineBackfillJob.State.DONE
        self.job.save()
        reprocess_legacy_pipeline_tick()  # should not raise
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose run --rm test pytest camp/apps/monitors/test_legacy_backfill.py::ReprocessLegacyPipelineTickTests -v`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Write the implementation**

```python
# camp/apps/monitors/tasks.py — add to imports
from camp.apps.monitors.legacy_backfill import monitors_with_incomplete_pipelines_in
```

```python
# camp/apps/monitors/tasks.py — new orchestrator
PIPELINE_BACKFILL_LOCK_STALE_SECONDS = 30
PIPELINE_BACKFILL_BATCH_STALE_MINUTES = 60
PIPELINE_BACKFILL_MAX_CONSECUTIVE_FAILURES = 5


@db_periodic_task(crontab(minute='*'), priority=1, queue='primary')
def reprocess_legacy_pipeline_tick():
    '''
    Drive one step of the active PipelineBackfillJob, if any. Never blocks on
    the sub-tasks it dispatches. See
    docs/superpowers/specs/2026-07-28-legacy-entries-backfill-design.md.
    '''
    now = timezone.now()

    with transaction.atomic():
        job = (
            PipelineBackfillJob.objects
            .select_for_update(skip_locked=True)
            .filter(state=PipelineBackfillJob.State.RUNNING)
            .filter(
                Q(locked_at__isnull=True) |
                Q(locked_at__lt=now - timedelta(seconds=PIPELINE_BACKFILL_LOCK_STALE_SECONDS))
            )
            .order_by('created')
            .first()
        )
        if job is None:
            return

        job.locked_at = now
        job.save(update_fields=['locked_at'])

        if job.pending_tasks > 0:
            stale_before = now - timedelta(minutes=PIPELINE_BACKFILL_BATCH_STALE_MINUTES)
            if job.phase_started_at and job.phase_started_at < stale_before:
                _pipeline_backfill_restart_batch(job)
            return

        if job.chunk_start is not None:
            _pipeline_backfill_complete_chunk(job)
        else:
            _pipeline_backfill_dispatch_chunk(job)


def _pipeline_backfill_dispatch_chunk(job):
    chunk_start = chunk_start_for(job.cursor, job.range_start, job.chunk_days)
    monitor_ids = monitors_with_incomplete_pipelines_in(chunk_start, job.cursor)

    job.chunk_start = chunk_start
    job.batch_id += 1
    job.pending_tasks = len(monitor_ids)
    job.phase_started_at = timezone.now()
    job.save()

    job_id = job.pk
    batch_id = job.batch_id
    chunk_end = job.cursor
    for monitor_id in monitor_ids:
        transaction.on_commit(
            lambda m=monitor_id: reprocess_monitor_chunk(job_id, str(m), chunk_start, chunk_end, batch_id)
        )


def _pipeline_backfill_complete_chunk(job):
    job.cursor = job.chunk_start
    job.chunk_start = None
    job.pending_tasks = 0
    job.consecutive_failures = 0
    job.last_error = ''
    if job.cursor <= job.range_start:
        job.state = PipelineBackfillJob.State.DONE
    job.save()


def _pipeline_backfill_restart_batch(job):
    job.consecutive_failures += 1
    job.last_error = (
        f'Batch {job.batch_id} stalled with {job.pending_tasks} pending task(s); restarting.'
    )

    if job.consecutive_failures >= PIPELINE_BACKFILL_MAX_CONSECUTIVE_FAILURES:
        job.pending_tasks = 0
        job.state = PipelineBackfillJob.State.FAILED
        job.save()
        return

    chunk_start = job.chunk_start
    monitor_ids = monitors_with_incomplete_pipelines_in(chunk_start, job.cursor)

    job.batch_id += 1
    job.pending_tasks = len(monitor_ids)
    job.phase_started_at = timezone.now()
    job.save()

    job_id = job.pk
    batch_id = job.batch_id
    chunk_end = job.cursor
    for monitor_id in monitor_ids:
        transaction.on_commit(
            lambda m=monitor_id: reprocess_monitor_chunk(job_id, str(m), chunk_start, chunk_end, batch_id)
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose run --rm test pytest camp/apps/monitors/test_legacy_backfill.py::ReprocessLegacyPipelineTickTests -v`
Expected: PASS

- [ ] **Step 5: Run the full new test file plus monitors/calibrations suites to check for regressions**

Run: `docker compose run --rm test pytest camp/apps/monitors/test_legacy_backfill.py camp/apps/monitors/tests.py camp/apps/calibrations/ -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add camp/apps/monitors/tasks.py camp/apps/monitors/test_legacy_backfill.py
git commit -m "feat(monitors): add reprocess_legacy_pipeline_tick orchestrator"
```

---

### Task 13: `reprocess_legacy_pipeline` management command

**Files:**
- Create: `camp/apps/monitors/management/commands/reprocess_legacy_pipeline.py`
- Test: `camp/apps/monitors/test_legacy_backfill.py`

**Interfaces:**
- Consumes: `PipelineBackfillJob` (Task 10).
- Produces: `manage.py reprocess_legacy_pipeline {start,status,cancel}`.

- [ ] **Step 1: Write the failing tests**

```python
# append to camp/apps/monitors/test_legacy_backfill.py
class ReprocessLegacyPipelineCommandTests(TestCase):
    def test_start_creates_job(self):
        out = StringIO()
        call_command('reprocess_legacy_pipeline', 'start', '--from', '2020-01-01', stdout=out)
        assert PipelineBackfillJob.objects.filter(state=PipelineBackfillJob.State.RUNNING).exists()
        assert 'Started' in out.getvalue()

    def test_start_refuses_second_job_without_force(self):
        call_command('reprocess_legacy_pipeline', 'start', '--from', '2020-01-01')
        try:
            call_command('reprocess_legacy_pipeline', 'start', '--from', '2020-01-01')
            assert False, 'expected CommandError'
        except CommandError:
            pass
        assert PipelineBackfillJob.objects.count() == 1

    def test_status_with_no_job(self):
        out = StringIO()
        call_command('reprocess_legacy_pipeline', 'status', stdout=out)
        assert 'No backfill job' in out.getvalue()

    def test_cancel_sets_state_done(self):
        call_command('reprocess_legacy_pipeline', 'start', '--from', '2020-01-01')
        call_command('reprocess_legacy_pipeline', 'cancel')
        job = PipelineBackfillJob.objects.first()
        assert job.state == PipelineBackfillJob.State.DONE
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose run --rm test pytest camp/apps/monitors/test_legacy_backfill.py::ReprocessLegacyPipelineCommandTests -v`
Expected: FAIL — no such management command.

- [ ] **Step 3: Write the implementation**

```python
# camp/apps/monitors/management/commands/reprocess_legacy_pipeline.py
from datetime import datetime

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.utils.dateparse import parse_date

from camp.utils.datetime import make_aware
from camp.apps.monitors.models import PipelineBackfillJob


class Command(BaseCommand):
    help = 'Start, monitor, or cancel the historical pipeline reprocessing job.'

    def add_arguments(self, parser):
        parser.add_argument('action', choices=['start', 'status', 'cancel'])
        parser.add_argument('--from', dest='date_from', metavar='YYYY-MM-DD',
            help='Earliest date to reprocess (required for start)')
        parser.add_argument('--to', dest='date_to', metavar='YYYY-MM-DD',
            help='Latest date to reprocess, exclusive (default: now)')
        parser.add_argument('--force', action='store_true',
            help='Replace an existing running/paused job instead of refusing to start a new one')
        parser.add_argument('--chunk-days', dest='chunk_days', type=int, default=7,
            help='Days per chunk (default: 7)')

    def handle(self, *args, **options):
        action = options['action']
        if action == 'start':
            self._start(options)
        elif action == 'status':
            self._status()
        elif action == 'cancel':
            self._cancel()

    def _start(self, options):
        if not options['date_from']:
            raise CommandError('--from is required for start')

        chunk_days = options['chunk_days']
        if chunk_days < 1:
            raise CommandError('--chunk-days must be at least 1')

        active = PipelineBackfillJob.objects.filter(
            state__in=[PipelineBackfillJob.State.RUNNING, PipelineBackfillJob.State.PAUSED],
        ).first()
        if active and not options['force']:
            raise CommandError(
                f'A pipeline reprocessing job is already {active.state} '
                f'(cursor {active.cursor:%Y-%m-%d}). Pass --force to replace it.'
            )
        if active and options['force']:
            active.delete()

        range_start = self._parse_date(options['date_from'])
        range_end = (
            self._parse_date(options['date_to'])
            if options['date_to']
            else timezone.now()
        )
        if range_start >= range_end:
            raise CommandError('--from must be before --to')

        PipelineBackfillJob.objects.create(
            cursor=range_end,
            range_start=range_start,
            range_end=range_end,
            chunk_days=chunk_days,
        )
        self.stdout.write(self.style.SUCCESS(
            f'Started pipeline reprocessing job: {range_start:%Y-%m-%d} -> {range_end:%Y-%m-%d} '
            f'({chunk_days}-day chunks)'
        ))

    def _status(self):
        job = PipelineBackfillJob.objects.order_by('-created').first()
        if job is None:
            self.stdout.write('No backfill job has been started.')
            return

        total_seconds = (job.range_end - job.range_start).total_seconds()
        done_seconds = (job.range_end - job.cursor).total_seconds()
        percent = 100 * done_seconds / total_seconds if total_seconds else 100

        self.stdout.write(f'State: {job.state}')
        self.stdout.write(f'Cursor: {job.cursor:%Y-%m-%d}')
        self.stdout.write(f'Range: {job.range_start:%Y-%m-%d} -> {job.range_end:%Y-%m-%d}')
        self.stdout.write(f'Chunk size: {job.chunk_days} day(s)')
        self.stdout.write(f'Progress: {percent:.1f}%')
        self.stdout.write(f'Entries processed: {job.entries_processed}')
        if job.last_error:
            self.stdout.write(self.style.WARNING(f'Last error: {job.last_error}'))

    def _cancel(self):
        job = PipelineBackfillJob.objects.filter(
            state__in=[PipelineBackfillJob.State.RUNNING, PipelineBackfillJob.State.PAUSED],
        ).first()
        if job is None:
            self.stdout.write('No active backfill job to cancel.')
            return
        job.state = PipelineBackfillJob.State.DONE
        job.save(update_fields=['state'])
        self.stdout.write(self.style.SUCCESS('Pipeline reprocessing job cancelled.'))

    def _parse_date(self, value):
        d = parse_date(value)
        if d is None:
            raise CommandError(f'Invalid date: {value!r}. Use YYYY-MM-DD.')
        return make_aware(datetime(d.year, d.month, d.day), settings.DEFAULT_TIMEZONE)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose run --rm test pytest camp/apps/monitors/test_legacy_backfill.py::ReprocessLegacyPipelineCommandTests -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add camp/apps/monitors/management/commands/reprocess_legacy_pipeline.py camp/apps/monitors/test_legacy_backfill.py
git commit -m "feat(monitors): add reprocess_legacy_pipeline management command"
```

---

### Task 14: `fix_purpleair_pressure` one-time repair command

**Files:**
- Create: `camp/apps/monitors/management/commands/fix_purpleair_pressure.py`
- Test: `camp/apps/monitors/test_legacy_backfill.py`

**Interfaces:**
- Consumes: legacy `Entry` model, `entries.Pressure`.
- Produces: `manage.py fix_purpleair_pressure [--dry-run]`.

- [ ] **Step 1: Write the failing tests**

```python
# append to camp/apps/monitors/test_legacy_backfill.py
class FixPurpleAirPressureCommandTests(TestCase):
    fixtures = ['purple-air.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.first()
        self.ts = _ts(2023, 1, 1)
        Entry.objects.create(
            monitor=self.monitor, sensor='a', timestamp=self.ts,
            location=self.monitor.location, pressure=Decimal('1013.25'),
        )

    def test_corrects_mislabeled_hpa_value(self):
        # Simulate the old buggy migration: raw hPa copied directly into `value`.
        bad_entry = entry_models.Pressure.objects.create(
            monitor=self.monitor, sensor='', timestamp=self.ts, location=self.monitor.location,
            stage=entry_models.Pressure.Stage.RAW, processor='', value=Decimal('1013.25'),
        )
        out = StringIO()
        call_command('fix_purpleair_pressure', stdout=out)
        bad_entry.refresh_from_db()
        expected = (Decimal('1013.25') / Decimal('1.33322')).quantize(Decimal('0.01'))
        assert bad_entry.value == expected
        assert 'Corrected 1' in out.getvalue()

    def test_leaves_already_correct_value_untouched(self):
        correct_value = (Decimal('1013.25') / Decimal('1.33322')).quantize(Decimal('0.01'))
        good_entry = entry_models.Pressure.objects.create(
            monitor=self.monitor, sensor='', timestamp=self.ts, location=self.monitor.location,
            stage=entry_models.Pressure.Stage.RAW, processor='', value=correct_value,
        )
        out = StringIO()
        call_command('fix_purpleair_pressure', stdout=out)
        good_entry.refresh_from_db()
        assert good_entry.value == correct_value
        assert 'Corrected 0' in out.getvalue()

    def test_dry_run_does_not_modify(self):
        bad_entry = entry_models.Pressure.objects.create(
            monitor=self.monitor, sensor='', timestamp=self.ts, location=self.monitor.location,
            stage=entry_models.Pressure.Stage.RAW, processor='', value=Decimal('1013.25'),
        )
        call_command('fix_purpleair_pressure', '--dry-run')
        bad_entry.refresh_from_db()
        assert bad_entry.value == Decimal('1013.25')
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose run --rm test pytest camp/apps/monitors/test_legacy_backfill.py::FixPurpleAirPressureCommandTests -v`
Expected: FAIL — no such management command.

- [ ] **Step 3: Write the implementation**

```python
# camp/apps/monitors/management/commands/fix_purpleair_pressure.py
from decimal import Decimal

from django.core.management.base import BaseCommand

from camp.apps.entries.models import Pressure
from camp.apps.monitors.models import Entry
from camp.apps.monitors.purpleair.models import PurpleAir


class Command(BaseCommand):
    help = (
        'One-time repair for PurpleAir Pressure RAW entries created by the old '
        'migrate_legacy_entry path, which copied legacy pressure (hPa) directly '
        'into `value` (mmHg) with no unit conversion. Recomputes each entry from '
        'its legacy source and updates in place if the value is wrong.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
            help='Report how many entries would be corrected without saving changes')

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        corrected = 0
        checked = 0

        queryset = Pressure.objects.filter(
            monitor__in=PurpleAir.objects.all(), stage=Pressure.Stage.RAW,
        ).iterator(chunk_size=1000)

        for entry in queryset:
            checked += 1
            legacy = (Entry.objects
                .filter(monitor_id=entry.monitor_id, timestamp=entry.timestamp, pressure__isnull=False)
                .first())
            if legacy is None:
                continue

            correct_value = (legacy.pressure / Decimal('1.33322')).quantize(Decimal('0.01'))
            if entry.value == correct_value:
                continue

            corrected += 1
            if not dry_run:
                entry.value = correct_value
                entry.save(update_fields=['value'])

        verb = 'Would correct' if dry_run else 'Corrected'
        self.stdout.write(self.style.SUCCESS(f'{verb} {corrected} of {checked} checked entries.'))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose run --rm test pytest camp/apps/monitors/test_legacy_backfill.py::FixPurpleAirPressureCommandTests -v`
Expected: PASS

- [ ] **Step 5: Run the full new test file one more time to confirm the whole suite is green**

Run: `docker compose run --rm test pytest camp/apps/monitors/test_legacy_backfill.py -v`
Expected: PASS (every test class from Tasks 1–14)

- [ ] **Step 6: Commit**

```bash
git add camp/apps/monitors/management/commands/fix_purpleair_pressure.py camp/apps/monitors/test_legacy_backfill.py
git commit -m "feat(monitors): add fix_purpleair_pressure one-time repair command"
```

---

## Final Verification

- [ ] Run the full project test suite to check for any cross-app regressions:

Run: `docker compose run --rm test pytest`
Expected: PASS (per `CLAUDE.md`, CI runs the bare full-suite `pytest`, not a scoped subset — this must be green before considering the plan complete)

- [ ] Confirm both management commands and the repair command are discoverable:

```bash
docker compose run --rm web python manage.py backfill_legacy_entries status
docker compose run --rm web python manage.py reprocess_legacy_pipeline status
docker compose run --rm web python manage.py fix_purpleair_pressure --dry-run
```

Expected: each runs without error (status commands report "No backfill job has been started"; the dry-run repair command reports a checked/corrected count, likely 0/0 in a fresh dev DB with no PurpleAir Pressure data yet).
