# Summary Backfill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a self-pacing Huey-driven mechanism that backfills `MonitorSummary`/`RegionSummary` rows (hourly through yearly) for the full 2020→present history, without flooding Redis and without manual supervision.

**Architecture:** A `SummaryBackfillJob` row tracks one backward-walking cursor. A periodic Huey task (`backfill_summaries_tick`, every 1 minute) drives a `phase` state machine (`idle` → `monitors` → `regions` → `idle`) — it fans work out to one Huey task per monitor (then per region) for each 7-day chunk, but never blocks waiting on them; it only checks a `pending_tasks` counter and returns. Rollups (daily/monthly/quarterly/seasonal/yearly) run inline once a chunk's fan-out drains, triggered by boundary-crossing detection rather than a separate phase.

**Tech Stack:** Django, `django_huey` (`db_task`/`db_periodic_task`), PostgreSQL (`select_for_update(skip_locked=True)`, `F()` expressions), `django_sqids`, `model_utils.TimeStampedModel`.

**Spec:** `docs/superpowers/specs/2026-07-13-summary-backfill-design.md`

## Global Constraints

- New models use `SqidsField` (`django_sqids`), never `SmallUUIDField` — `sqid = SqidsField(alphabet=shuffle_alphabet('summaries.SummaryBackfillJob'))`.
- Verbose names use `_()` as the first positional arg: `CharField(_('state'), ...)`.
- Don't align `=` signs in field definitions.
- Tests use plain `assert` / `pytest.raises`, inherit from `django.test.TestCase`, no `self.assertFoo()`.
- Never `git add -A` — stage files explicitly.
- No co-authored-by lines in commits.
- Run tests via `docker compose run --rm test pytest camp/apps/summaries/... -v`.
- **Huey `.call_local()` gotcha:** calling a `@db_task`/`@db_periodic_task`-decorated function bare (e.g. `backfill_monitor_chunk(...)`) always returns a Huey `Result` wrapper, never the function's real return value — even under `immediate=True` in tests. It still executes synchronously (side effects happen), so tests that only assert on DB state after a bare call are fine; only tests needing the actual return value must use `.call_local(...)`.
- **`transaction.on_commit` in tests:** Django's `TestCase` wraps each test in an outer transaction that's rolled back, not committed — so `transaction.on_commit()` callbacks registered inside application code are captured but never fire by default. Any test that needs to observe the effects of dispatched sub-tasks must wrap the call in `with self.captureOnCommitCallbacks(execute=True): ...`.

---

## File Structure

- Create: `camp/apps/summaries/backfill.py` — pure chunk/boundary helpers + per-monitor/per-region aggregation (no Huey, no model dependencies beyond `Monitor`/`Region`/`MonitorSummary`/`RegionSummary`).
- Modify: `camp/apps/summaries/models.py` — add `SummaryBackfillJob`.
- Create: `camp/apps/summaries/migrations/0005_summarybackfilljob.py`.
- Modify: `camp/apps/summaries/management/commands/rebuild_summaries.py` — delegate per-item computation to `backfill.py`.
- Create: `camp/apps/summaries/management/commands/backfill_summaries.py` — `start`/`status`/`cancel`.
- Modify: `camp/apps/summaries/tasks.py` — add `backfill_monitor_chunk`, `backfill_region_chunk`, `backfill_summaries_tick`.
- Modify: `camp/apps/summaries/admin.py` — register `SummaryBackfillJob`.
- Create: `camp/apps/summaries/test_backfill.py` — all new tests (kept separate from the existing 1194-line `tests.py` rather than growing it further; matches this codebase's existing precedent of `test_*.py` files for focused subsystems, e.g. `camp/apps/calibrations/tests/`).

---

### Task 1: Chunk & rollup-boundary helpers (pure functions)

**Files:**
- Create: `camp/apps/summaries/backfill.py`
- Test: `camp/apps/summaries/test_backfill.py`

**Interfaces:**
- Produces: `chunk_start_for(cursor, range_start) -> datetime`, `hour_range(start, end) -> Iterator[datetime]`, `iter_chunk_days(chunk_start, chunk_end) -> Iterator[datetime]`, `daily_rollup_window(day) -> tuple`, `higher_rollup_windows(day) -> list[tuple]`. Each window tuple is `(target_resolution, source_resolution, window_start, window_end)` using `BaseSummary.Resolution` values.

- [ ] **Step 1: Write the failing tests**

```python
# camp/apps/summaries/test_backfill.py
from datetime import datetime, timedelta

from django.conf import settings
from django.test import TestCase

from camp.utils.datetime import make_aware
from camp.apps.summaries.models import BaseSummary
from camp.apps.summaries.backfill import (
    chunk_start_for,
    hour_range,
    iter_chunk_days,
    daily_rollup_window,
    higher_rollup_windows,
)


def _day(y, m, d):
    return make_aware(datetime(y, m, d), settings.DEFAULT_TIMEZONE)


class ChunkStartForTests(TestCase):
    def test_steps_back_seven_days(self):
        cursor = _day(2023, 7, 15)
        range_start = _day(2020, 1, 1)
        assert chunk_start_for(cursor, range_start) == cursor - timedelta(days=7)

    def test_clamps_to_range_start(self):
        cursor = _day(2020, 1, 4)
        range_start = _day(2020, 1, 1)
        assert chunk_start_for(cursor, range_start) == range_start


class HourRangeTests(TestCase):
    def test_yields_each_hour_exclusive_of_end(self):
        start = _day(2023, 1, 1)
        end = start + timedelta(hours=3)
        hours = list(hour_range(start, end))
        assert hours == [start, start + timedelta(hours=1), start + timedelta(hours=2)]


class IterChunkDaysTests(TestCase):
    def test_yields_each_day_exclusive_of_end(self):
        start = _day(2023, 1, 1)
        end = start + timedelta(days=3)
        days = list(iter_chunk_days(start, end))
        assert days == [start, start + timedelta(days=1), start + timedelta(days=2)]


class DailyRollupWindowTests(TestCase):
    def test_returns_daily_window(self):
        day = _day(2023, 7, 15)
        target, source, window_start, window_end = daily_rollup_window(day)
        assert target == BaseSummary.Resolution.DAILY
        assert source == BaseSummary.Resolution.HOURLY
        assert window_start == day
        assert window_end == day + timedelta(days=1)


class HigherRollupWindowsTests(TestCase):
    def test_mid_month_day_has_no_higher_windows(self):
        assert higher_rollup_windows(_day(2023, 7, 15)) == []

    def test_ordinary_month_start_rolls_up_month_only(self):
        windows = higher_rollup_windows(_day(2023, 8, 1))
        resolutions = [w[0] for w in windows]
        assert resolutions == [BaseSummary.Resolution.MONTHLY]

    def test_quarter_start_month_cascades_to_quarterly(self):
        windows = higher_rollup_windows(_day(2023, 7, 1))
        resolutions = [w[0] for w in windows]
        assert BaseSummary.Resolution.MONTHLY in resolutions
        assert BaseSummary.Resolution.QUARTERLY in resolutions
        assert BaseSummary.Resolution.SEASONAL not in resolutions
        assert BaseSummary.Resolution.YEARLY not in resolutions

    def test_season_start_month_cascades_to_seasonal(self):
        windows = higher_rollup_windows(_day(2023, 6, 1))
        resolutions = [w[0] for w in windows]
        assert BaseSummary.Resolution.SEASONAL in resolutions

    def test_december_is_season_start_but_not_quarter_start(self):
        windows = higher_rollup_windows(_day(2023, 12, 1))
        resolutions = [w[0] for w in windows]
        assert BaseSummary.Resolution.SEASONAL in resolutions
        assert BaseSummary.Resolution.QUARTERLY not in resolutions

    def test_january_cascades_to_quarterly_and_yearly(self):
        windows = higher_rollup_windows(_day(2023, 1, 1))
        resolutions = [w[0] for w in windows]
        assert BaseSummary.Resolution.MONTHLY in resolutions
        assert BaseSummary.Resolution.QUARTERLY in resolutions
        assert BaseSummary.Resolution.YEARLY in resolutions

    def test_quarterly_window_spans_three_months(self):
        windows = higher_rollup_windows(_day(2023, 7, 1))
        quarterly = next(w for w in windows if w[0] == BaseSummary.Resolution.QUARTERLY)
        _, _, window_start, window_end = quarterly
        assert window_start == _day(2023, 7, 1)
        assert window_end == _day(2023, 10, 1)

    def test_yearly_window_spans_twelve_months(self):
        windows = higher_rollup_windows(_day(2023, 1, 1))
        yearly = next(w for w in windows if w[0] == BaseSummary.Resolution.YEARLY)
        _, _, window_start, window_end = yearly
        assert window_start == _day(2023, 1, 1)
        assert window_end == _day(2024, 1, 1)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose run --rm test pytest camp/apps/summaries/test_backfill.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'camp.apps.summaries.backfill'`

- [ ] **Step 3: Write the implementation**

```python
# camp/apps/summaries/backfill.py
from datetime import datetime, timedelta

from django.conf import settings

from camp.utils.datetime import make_aware
from camp.apps.summaries.models import BaseSummary


CHUNK_DAYS = 7


def chunk_start_for(cursor, range_start):
    """The lower bound of the next chunk to process, walking backward from cursor."""
    return max(cursor - timedelta(days=CHUNK_DAYS), range_start)


def hour_range(start, end):
    """Yield each hourly datetime in [start, end)."""
    current = start
    while current < end:
        yield current
        current += timedelta(hours=1)


def iter_chunk_days(chunk_start, chunk_end):
    """Yield each day (midnight-aligned datetime) in [chunk_start, chunk_end)."""
    day = chunk_start
    while day < chunk_end:
        yield day
        day += timedelta(days=1)


def _months_later(day, months):
    """Advance a day-1-aligned datetime by `months` calendar months, re-localizing for DST."""
    total = day.month - 1 + months
    year = day.year + total // 12
    month = total % 12 + 1
    return make_aware(datetime(year, month, 1), settings.DEFAULT_TIMEZONE)


def daily_rollup_window(day):
    """The (target, source, window_start, window_end) tuple to roll up a single day."""
    return (BaseSummary.Resolution.DAILY, BaseSummary.Resolution.HOURLY, day, day + timedelta(days=1))


def higher_rollup_windows(day):
    """
    Return the (target, source, window_start, window_end) rollup windows that
    become fully covered once `day` — the earliest day of a chunk, walking
    backward — has been processed. Empty unless `day` is the first of a
    month: only then can a month (and possibly quarter/season/year) be
    confirmed complete, since every later day in that period was necessarily
    already processed on an earlier (more recent) tick.
    """
    if day.day != 1:
        return []

    windows = [(
        BaseSummary.Resolution.MONTHLY, BaseSummary.Resolution.DAILY,
        day, _months_later(day, 1),
    )]

    if day.month in (1, 4, 7, 10):
        windows.append((
            BaseSummary.Resolution.QUARTERLY, BaseSummary.Resolution.MONTHLY,
            day, _months_later(day, 3),
        ))

    if day.month in (12, 3, 6, 9):
        windows.append((
            BaseSummary.Resolution.SEASONAL, BaseSummary.Resolution.MONTHLY,
            day, _months_later(day, 3),
        ))

    if day.month == 1:
        windows.append((
            BaseSummary.Resolution.YEARLY, BaseSummary.Resolution.MONTHLY,
            day, _months_later(day, 12),
        ))

    return windows
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose run --rm test pytest camp/apps/summaries/test_backfill.py -v`
Expected: PASS (all `ChunkStartForTests`, `HourRangeTests`, `IterChunkDaysTests`, `DailyRollupWindowTests`, `HigherRollupWindowsTests`)

- [ ] **Step 5: Commit**

```bash
git add camp/apps/summaries/backfill.py camp/apps/summaries/test_backfill.py
git commit -m "feat(summaries): add chunk and rollup-boundary helpers for backfill"
```

---

### Task 2: Per-monitor / per-region aggregation + data-presence queries

**Files:**
- Modify: `camp/apps/summaries/backfill.py`
- Test: `camp/apps/summaries/test_backfill.py`

**Interfaces:**
- Consumes: `Stage` from `camp.apps.entries.stages`, `compute_stats`/`compute_region_summary` from `camp.apps.summaries.aggregators`, `Monitor` from `camp.apps.monitors.models`, `Region` from `camp.apps.regions.models`, `MonitorSummary`/`RegionSummary` from `camp.apps.summaries.models`.
- Produces: `backfill_monitor_hours(monitor, chunk_start, chunk_end, entry_models) -> int`, `backfill_region_hours(region, hours, monitor_grades) -> int`, `monitors_with_data_in(chunk_start, chunk_end, entry_models) -> list`, `regions_with_monitors() -> list`.

- [ ] **Step 1: Write the failing tests**

```python
# Append to camp/apps/summaries/test_backfill.py
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from camp.apps.entries.models import PM25
from camp.apps.monitors.bam.models import BAM1022
from camp.apps.monitors.models import Monitor
from camp.apps.monitors.purpleair.models import PurpleAir
from camp.apps.regions.models import Region
from camp.apps.summaries.models import BaseSummary, MonitorSummary, RegionSummary
from camp.apps.summaries.backfill import (
    backfill_monitor_hours,
    backfill_region_hours,
    monitors_with_data_in,
    regions_with_monitors,
)


class BackfillMonitorHoursTests(TestCase):
    fixtures = ['purple-air.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.first()
        self.start = timezone.now().replace(minute=0, second=0, microsecond=0) - timedelta(hours=3)
        self.end = self.start + timedelta(hours=2)

    def _make_entry(self, hour_offset, value):
        return PM25.objects.create(
            monitor=self.monitor,
            timestamp=self.start + timedelta(hours=hour_offset, minutes=5),
            stage=PM25.Stage.RAW,
            processor='',
            value=value,
            location=self.monitor.location,
        )

    def test_creates_one_summary_per_hour_with_data(self):
        self._make_entry(0, 10.0)
        self._make_entry(1, 20.0)
        count = backfill_monitor_hours(self.monitor, self.start, self.end, [PM25])
        assert count == 2
        assert MonitorSummary.objects.filter(monitor=self.monitor, resolution=BaseSummary.Resolution.HOURLY).count() == 2

    def test_skips_hours_with_no_entries(self):
        self._make_entry(0, 10.0)
        backfill_monitor_hours(self.monitor, self.start, self.end, [PM25])
        assert MonitorSummary.objects.count() == 1

    def test_excludes_entries_outside_range(self):
        self._make_entry(-1, 999.0)  # before self.start
        backfill_monitor_hours(self.monitor, self.start, self.end, [PM25])
        assert MonitorSummary.objects.count() == 0

    def test_is_idempotent_on_rerun(self):
        self._make_entry(0, 10.0)
        backfill_monitor_hours(self.monitor, self.start, self.end, [PM25])
        backfill_monitor_hours(self.monitor, self.start, self.end, [PM25])
        assert MonitorSummary.objects.count() == 1


class MonitorsWithDataInTests(TestCase):
    fixtures = ['purple-air.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.first()
        self.start = timezone.now().replace(minute=0, second=0, microsecond=0) - timedelta(hours=2)
        self.end = self.start + timedelta(hours=1)

    def test_includes_monitor_with_entry_in_range(self):
        PM25.objects.create(
            monitor=self.monitor, timestamp=self.start + timedelta(minutes=5),
            stage=PM25.Stage.RAW, processor='', value=10.0, location=self.monitor.location,
        )
        assert self.monitor.pk in monitors_with_data_in(self.start, self.end, [PM25])

    def test_excludes_monitor_with_no_entries(self):
        assert self.monitor.pk not in monitors_with_data_in(self.start, self.end, [PM25])


class RegionsWithMonitorsTests(TestCase):
    fixtures = ['purple-air.yaml', 'regions.yaml']

    def test_returns_region_containing_a_monitor(self):
        region = Region.objects.filter(boundary__isnull=False).first()
        if not region:
            self.skipTest('no region with boundary in fixtures')
        monitor = PurpleAir.objects.first()
        monitor.position = region.boundary.geometry.centroid
        monitor.save()
        assert region.pk in regions_with_monitors()

    def test_excludes_region_with_no_monitors(self):
        region = Region.objects.filter(boundary__isnull=False).first()
        if not region:
            self.skipTest('no region with boundary in fixtures')
        assert region.pk not in regions_with_monitors()


class BackfillRegionHoursTests(TestCase):
    fixtures = ['purple-air.yaml', 'regions.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.first()
        self.region = Region.objects.filter(boundary__isnull=False).first()
        if not self.region:
            self.skipTest('no region with boundary in fixtures')
        self.monitor.position = self.region.boundary.geometry.centroid
        self.monitor.save()
        self.hour = timezone.now().replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
        MonitorSummary.objects.create(
            monitor=self.monitor, timestamp=self.hour,
            resolution=BaseSummary.Resolution.HOURLY, entry_type='pm25', processor='',
            count=10, expected_count=30, sum_value=200.0, sum_of_squares=4000.0,
            minimum=20.0, maximum=20.0, mean=20.0, stddev=0.0, p25=20.0, p75=20.0,
            tdigest={'C': [[20.0, 10]], 'n': 10}, is_complete=False,
        )

    def test_creates_region_summary_from_monitor_summary(self):
        monitor_grades = {self.monitor.pk: Monitor.Grade.LCS}
        count = backfill_region_hours(self.region, [self.hour], monitor_grades)
        assert count == 1
        assert RegionSummary.objects.filter(region=self.region, timestamp=self.hour).exists()

    def test_skips_hours_with_no_monitor_summaries(self):
        monitor_grades = {self.monitor.pk: Monitor.Grade.LCS}
        other_hour = self.hour - timedelta(hours=5)
        count = backfill_region_hours(self.region, [other_hour], monitor_grades)
        assert count == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose run --rm test pytest camp/apps/summaries/test_backfill.py -v`
Expected: FAIL with `ImportError: cannot import name 'backfill_monitor_hours'`

- [ ] **Step 3: Write the implementation**

```python
# Add to camp/apps/summaries/backfill.py, after the existing imports
from collections import defaultdict
from functools import reduce
import operator

from django.db.models import Exists, OuterRef, Q

from camp.apps.entries.stages import Stage
from camp.apps.monitors.models import Monitor
from camp.apps.regions.models import Region
from camp.apps.summaries.aggregators import compute_stats, compute_region_summary
from camp.apps.summaries.models import MonitorSummary, RegionSummary
```

```python
# Add to the end of camp/apps/summaries/backfill.py

def monitors_with_data_in(chunk_start, chunk_end, entry_models):
    """Monitor ids with at least one entry of any given type in [chunk_start, chunk_end)."""
    conditions = [
        Exists(EntryModel.objects.filter(
            monitor_id=OuterRef('pk'),
            timestamp__gte=chunk_start,
            timestamp__lt=chunk_end,
        ))
        for EntryModel in entry_models
    ]
    combined = reduce(operator.or_, conditions)
    return list(Monitor.objects.filter(combined).values_list('pk', flat=True).distinct())


def regions_with_monitors():
    """Region ids that have at least one monitor located inside their boundary."""
    return list(
        Region.objects
        .filter(
            Exists(Monitor.objects.filter(
                position__isnull=False,
                position__intersects=OuterRef('boundary__geometry'),
            )),
            boundary__isnull=False,
        )
        .values_list('pk', flat=True)
    )


def backfill_monitor_hours(monitor, chunk_start, chunk_end, entry_models):
    """
    Compute and upsert hourly MonitorSummary rows for one monitor across
    [chunk_start, chunk_end). One query per entry model, regardless of how
    many hours the chunk spans. Returns the number of summaries written.
    """
    to_upsert = []
    for EntryModel in entry_models:
        rows = (
            EntryModel.objects
            .filter(
                monitor_id=monitor.pk,
                timestamp__gte=chunk_start,
                timestamp__lt=chunk_end,
            )
            .filter(Q(stage=Stage.RAW, processor='') | Q(stage=Stage.CALIBRATED))
            .values_list('timestamp', 'processor', 'value')
        )

        groups = defaultdict(list)
        for ts, processor, value in rows:
            if value is not None:
                hour = ts.replace(minute=0, second=0, microsecond=0)
                groups[(hour, processor)].append(float(value))

        for (hour, processor), values in groups.items():
            stats = compute_stats(values, monitor.expected_hourly_entries or 1)
            if stats is None:
                continue
            to_upsert.append(MonitorSummary(
                monitor_id=monitor.pk,
                timestamp=hour,
                resolution=BaseSummary.Resolution.HOURLY,
                entry_type=EntryModel.entry_type,
                processor=processor,
                **stats,
            ))

    if to_upsert:
        MonitorSummary.objects.bulk_create(
            to_upsert,
            update_conflicts=True,
            unique_fields=['monitor', 'entry_type', 'processor', 'resolution', 'timestamp'],
            update_fields=[
                'count', 'expected_count', 'sum_value', 'sum_of_squares',
                'minimum', 'maximum', 'mean', 'stddev', 'p25', 'p75',
                'tdigest', 'is_complete',
            ],
        )
    return len(to_upsert)


def backfill_region_hours(region, hours, monitor_grades):
    """
    Compute and upsert hourly RegionSummary rows for one region across the
    given hours, using precomputed monitor_grades ({monitor_id: grade}) to
    avoid a geospatial query per hour. Returns the number of summaries written.
    """
    to_upsert = []
    for hour in hours:
        entry_types = list(
            MonitorSummary.objects
            .filter(timestamp=hour, resolution=BaseSummary.Resolution.HOURLY)
            .values_list('entry_type', flat=True)
            .distinct()
        )
        for entry_type in entry_types:
            stats = compute_region_summary(region, hour, entry_type, monitor_grades=monitor_grades)
            if stats is None:
                continue
            to_upsert.append(RegionSummary(
                region=region,
                timestamp=hour,
                resolution=BaseSummary.Resolution.HOURLY,
                entry_type=entry_type,
                **stats,
            ))

    if to_upsert:
        RegionSummary.objects.bulk_create(
            to_upsert,
            update_conflicts=True,
            unique_fields=['region', 'entry_type', 'resolution', 'timestamp'],
            update_fields=[
                'count', 'weight', 'expected_count', 'sum_value', 'sum_of_squares',
                'minimum', 'maximum', 'mean', 'stddev', 'p25', 'p75',
                'tdigest', 'station_count',
            ],
        )
    return len(to_upsert)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose run --rm test pytest camp/apps/summaries/test_backfill.py -v`
Expected: PASS (all tests, including the ones from Task 1)

- [ ] **Step 5: Commit**

```bash
git add camp/apps/summaries/backfill.py camp/apps/summaries/test_backfill.py
git commit -m "feat(summaries): add per-monitor/per-region backfill aggregation"
```

---

### Task 3: Refactor `rebuild_summaries.py` to use the shared `backfill.py` functions

**Files:**
- Modify: `camp/apps/summaries/management/commands/rebuild_summaries.py`
- Test: `camp/apps/summaries/tests.py` (existing `RebuildSummariesCommandTests` — must stay green, no new tests needed)

**Interfaces:**
- Consumes: `backfill_monitor_hours`, `backfill_region_hours` from `camp.apps.summaries.backfill` (Task 2).

This task removes the duplicated aggregation logic from the command's private methods, replacing it with calls to the functions built in Task 2. This is a refactor — the existing `RebuildSummariesCommandTests` (in `camp/apps/summaries/tests.py`) are the regression check; no new tests are written here.

- [ ] **Step 1: Confirm the existing tests pass before touching anything**

Run: `docker compose run --rm test pytest camp/apps/summaries/tests.py::RebuildSummariesCommandTests -v`
Expected: PASS (baseline, before refactor)

- [ ] **Step 2: Update imports**

In `camp/apps/summaries/management/commands/rebuild_summaries.py`, replace:

```python
import calendar
import sys
from collections import defaultdict
from datetime import datetime, timedelta

import tqdm

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.utils.dateparse import parse_date

from django.conf import settings
from django.db.models import Q

from camp.utils.datetime import make_aware
from camp.apps.entries.stages import Stage
from camp.apps.summaries.aggregators import compute_stats, compute_region_summary
from camp.apps.summaries.models import BaseSummary, MonitorSummary, RegionSummary
from camp.apps.summaries.tasks import (
    get_summarizable_entry_models,
    rollup_monitor_summaries,
    rollup_region_summaries,
)
```

with:

```python
import calendar
from datetime import datetime, timedelta

import tqdm

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.utils.dateparse import parse_date

from django.conf import settings
from django.db.models import Q

from camp.utils.datetime import make_aware
from camp.apps.entries.stages import Stage
from camp.apps.summaries.backfill import backfill_monitor_hours, backfill_region_hours
from camp.apps.summaries.models import BaseSummary, MonitorSummary, RegionSummary
from camp.apps.summaries.tasks import (
    get_summarizable_entry_models,
    rollup_monitor_summaries,
    rollup_region_summaries,
)
```

(`defaultdict`, `sys`, and the `aggregators` import are dropped — they were only used inside the two methods being replaced. `Q` and `Stage` stay — the `--async` enqueue methods further down the file still use them.)

- [ ] **Step 3: Replace the two backfill methods**

Replace the `_backfill_monitor_summaries` method (originally lines 123–174) with:

```python
    def _backfill_monitor_summaries(self, monitors, start, end, entry_models):
        self.stdout.write(f'\nComputing hourly monitor summaries...')
        self.stdout.flush()
        for monitor in tqdm.tqdm(monitors, file=self.stdout, dynamic_ncols=True):
            backfill_monitor_hours(monitor, start, end, entry_models)
```

Replace the `_backfill_region_summaries` method (originally lines 176–223) with:

```python
    def _backfill_region_summaries(self, regions, hours):
        region_monitor_grades = {}
        for region in regions:
            if region.boundary:
                region_monitor_grades[region.pk] = dict(
                    region.monitors.with_grade().values_list('pk', 'grade')
                )

        self.stdout.write(f'\nComputing hourly region summaries...')
        self.stdout.flush()

        for region in tqdm.tqdm(regions, file=self.stdout, dynamic_ncols=True):
            monitor_grades = region_monitor_grades.get(region.pk)
            if not monitor_grades:
                continue
            backfill_region_hours(region, hours, monitor_grades)
```

- [ ] **Step 4: Update the call site in `handle()`**

Find this block (originally around line 107–110):

```python
            else:
                monitors_by_id = {m.pk: m for m in monitors}
                self._backfill_monitor_summaries(monitors_by_id, hours, entry_models)
                self._rollup(rollup_monitor_summaries, 'monitor', monitor_ids, start, end)
```

Replace with:

```python
            else:
                self._backfill_monitor_summaries(monitors, start, end, entry_models)
                self._rollup(rollup_monitor_summaries, 'monitor', monitor_ids, start, end)
```

(The region call site, `self._backfill_region_summaries(list(regions), hours)`, is unchanged — same signature.)

- [ ] **Step 5: Run the existing tests to verify they still pass**

Run: `docker compose run --rm test pytest camp/apps/summaries/tests.py::RebuildSummariesCommandTests -v`
Expected: PASS — same behavior, refactored internals.

Also run the full summaries suite to make sure nothing else broke:

Run: `docker compose run --rm test pytest camp/apps/summaries/tests.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add camp/apps/summaries/management/commands/rebuild_summaries.py
git commit -m "refactor(summaries): delegate rebuild_summaries backfill logic to backfill.py"
```

---

### Task 4: `SummaryBackfillJob` model + migration

**Files:**
- Modify: `camp/apps/summaries/models.py`
- Create: `camp/apps/summaries/migrations/0005_summarybackfilljob.py`
- Test: `camp/apps/summaries/test_backfill.py`

**Interfaces:**
- Produces: `SummaryBackfillJob` model with `State` and `Phase` `TextChoices`, fields: `sqid`, `state`, `phase`, `cursor`, `chunk_start`, `range_start`, `range_end`, `pending_tasks`, `batch_id`, `phase_started_at`, `locked_at`, `consecutive_failures`, `last_error`, `created`, `modified` (from `TimeStampedModel`).

- [ ] **Step 1: Write the failing test**

```python
# Append to camp/apps/summaries/test_backfill.py
from django.test import TestCase
from django.utils import timezone

from camp.apps.summaries.models import SummaryBackfillJob


class SummaryBackfillJobTests(TestCase):
    def _make_job(self, **kwargs):
        now = timezone.now()
        defaults = dict(
            cursor=now,
            range_start=now - timedelta(days=365),
            range_end=now,
        )
        defaults.update(kwargs)
        return SummaryBackfillJob.objects.create(**defaults)

    def test_defaults(self):
        job = self._make_job()
        assert job.state == SummaryBackfillJob.State.RUNNING
        assert job.phase == SummaryBackfillJob.Phase.IDLE
        assert job.pending_tasks == 0
        assert job.batch_id == 0
        assert job.consecutive_failures == 0
        assert job.last_error == ''
        assert job.chunk_start is None
        assert job.locked_at is None
        assert job.sqid
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose run --rm test pytest camp/apps/summaries/test_backfill.py::SummaryBackfillJobTests -v`
Expected: FAIL with `ImportError: cannot import name 'SummaryBackfillJob'`

- [ ] **Step 3: Add the model**

Append to `camp/apps/summaries/models.py`:

```python
from django_sqids import SqidsField, shuffle_alphabet
from model_utils.models import TimeStampedModel


class SummaryBackfillJob(TimeStampedModel):
    class State(models.TextChoices):
        RUNNING = 'running', _('Running')
        PAUSED = 'paused', _('Paused')
        DONE = 'done', _('Done')
        FAILED = 'failed', _('Failed')

    class Phase(models.TextChoices):
        IDLE = 'idle', _('Idle')
        MONITORS = 'monitors', _('Monitors')
        REGIONS = 'regions', _('Regions')

    sqid = SqidsField(alphabet=shuffle_alphabet('summaries.SummaryBackfillJob'))

    state = models.CharField(_('state'), max_length=10, choices=State.choices, default=State.RUNNING)
    phase = models.CharField(_('phase'), max_length=10, choices=Phase.choices, default=Phase.IDLE)

    cursor = models.DateTimeField(_('cursor'))
    chunk_start = models.DateTimeField(_('chunk start'), null=True, blank=True)
    range_start = models.DateTimeField(_('range start'))
    range_end = models.DateTimeField(_('range end'))

    pending_tasks = models.PositiveIntegerField(_('pending tasks'), default=0)
    batch_id = models.PositiveIntegerField(_('batch id'), default=0)
    phase_started_at = models.DateTimeField(_('phase started at'), null=True, blank=True)
    locked_at = models.DateTimeField(_('locked at'), null=True, blank=True)

    consecutive_failures = models.PositiveSmallIntegerField(_('consecutive failures'), default=0)
    last_error = models.TextField(_('last error'), blank=True, default='')

    def __str__(self):
        return f'{self.state} ({self.phase}) @ {self.cursor:%Y-%m-%d}'
```

- [ ] **Step 4: Generate and inspect the migration**

Run: `docker compose run --rm web python manage.py makemigrations summaries`
Expected: creates `camp/apps/summaries/migrations/0005_summarybackfilljob.py`

- [ ] **Step 5: Run test to verify it passes**

Run: `docker compose run --rm test pytest camp/apps/summaries/test_backfill.py::SummaryBackfillJobTests -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add camp/apps/summaries/models.py camp/apps/summaries/migrations/0005_summarybackfilljob.py camp/apps/summaries/test_backfill.py
git commit -m "feat(summaries): add SummaryBackfillJob model"
```

---

### Task 5: Admin registration

**Files:**
- Modify: `camp/apps/summaries/admin.py`

No new test — this codebase doesn't test `ModelAdmin` registrations for `MonitorSummaryAdmin`/`RegionSummaryAdmin` either; a malformed admin class would fail at Django's app-loading system checks, which every test run already exercises.

- [ ] **Step 1: Register the admin**

Add to `camp/apps/summaries/admin.py`:

```python
from camp.apps.summaries.models import MonitorSummary, RegionSummary, SummaryBackfillJob
```

(replacing the existing `from camp.apps.summaries.models import MonitorSummary, RegionSummary` import line)

```python
@admin.register(SummaryBackfillJob)
class SummaryBackfillJobAdmin(admin.ModelAdmin):
    list_display = ['state', 'phase', 'cursor', 'range_start', 'range_end', 'pending_tasks', 'consecutive_failures', 'modified']
    list_filter = ['state', 'phase']
    ordering = ['-created']
    readonly_fields = [f.name for f in SummaryBackfillJob._meta.get_fields() if isinstance(f, Field) and f.name != 'state']
```

- [ ] **Step 2: Verify the app loads cleanly**

Run: `docker compose run --rm test pytest camp/apps/summaries/ -v`
Expected: PASS (a broken `ModelAdmin` would raise at Django app startup, failing the whole run)

- [ ] **Step 3: Commit**

```bash
git add camp/apps/summaries/admin.py
git commit -m "feat(summaries): register SummaryBackfillJob in admin"
```

---

### Task 6: `backfill_summaries` management command — `start` / `status` / `cancel`

**Files:**
- Create: `camp/apps/summaries/management/commands/backfill_summaries.py`
- Test: `camp/apps/summaries/test_backfill.py`

**Interfaces:**
- Consumes: `SummaryBackfillJob` (Task 4).

- [ ] **Step 1: Write the failing tests**

```python
# Append to camp/apps/summaries/test_backfill.py
from datetime import datetime

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
import pytest

from camp.utils.datetime import make_aware
from camp.apps.summaries.models import SummaryBackfillJob


class BackfillSummariesCommandTests(TestCase):
    def _run(self, *args):
        call_command('backfill_summaries', *args, stdout=open('/dev/null', 'w'))

    def test_start_creates_running_idle_job(self):
        self._run('start', '--from=2020-01-01', '--to=2020-02-01')
        job = SummaryBackfillJob.objects.get()
        assert job.state == SummaryBackfillJob.State.RUNNING
        assert job.phase == SummaryBackfillJob.Phase.IDLE
        assert job.range_start == make_aware(datetime(2020, 1, 1), settings.DEFAULT_TIMEZONE)
        assert job.range_end == make_aware(datetime(2020, 2, 1), settings.DEFAULT_TIMEZONE)
        assert job.cursor == job.range_end

    def test_start_requires_from(self):
        with pytest.raises((CommandError, SystemExit)):
            self._run('start')

    def test_start_refuses_second_job_without_force(self):
        self._run('start', '--from=2020-01-01', '--to=2020-02-01')
        with pytest.raises((CommandError, SystemExit)):
            self._run('start', '--from=2019-01-01', '--to=2019-02-01')

    def test_start_force_replaces_existing_job(self):
        self._run('start', '--from=2020-01-01', '--to=2020-02-01')
        self._run('start', '--from=2019-01-01', '--to=2019-02-01', '--force')
        job = SummaryBackfillJob.objects.get()
        assert job.range_start == make_aware(datetime(2019, 1, 1), settings.DEFAULT_TIMEZONE)

    def test_status_with_no_job_does_not_raise(self):
        self._run('status')

    def test_status_with_job_does_not_raise(self):
        self._run('start', '--from=2020-01-01', '--to=2020-02-01')
        self._run('status')

    def test_cancel_sets_state_done(self):
        self._run('start', '--from=2020-01-01', '--to=2020-02-01')
        self._run('cancel')
        job = SummaryBackfillJob.objects.get()
        assert job.state == SummaryBackfillJob.State.DONE

    def test_cancel_with_no_active_job_does_not_raise(self):
        self._run('cancel')
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose run --rm test pytest camp/apps/summaries/test_backfill.py::BackfillSummariesCommandTests -v`
Expected: FAIL with `CommandError: Unknown command: 'backfill_summaries'`

- [ ] **Step 3: Write the command**

```python
# camp/apps/summaries/management/commands/backfill_summaries.py
from datetime import datetime

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.utils.dateparse import parse_date

from camp.utils.datetime import make_aware
from camp.apps.summaries.models import SummaryBackfillJob


class Command(BaseCommand):
    help = 'Start, monitor, or cancel the automated full-history summary backfill job.'

    def add_arguments(self, parser):
        parser.add_argument('action', choices=['start', 'status', 'cancel'])
        parser.add_argument('--from', dest='date_from', metavar='YYYY-MM-DD',
            help='Earliest date to backfill (required for start)')
        parser.add_argument('--to', dest='date_to', metavar='YYYY-MM-DD',
            help='Latest date to backfill, exclusive (default: start of current month)')
        parser.add_argument('--force', action='store_true',
            help='Replace an existing running/paused job instead of refusing to start a new one')

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

        active = SummaryBackfillJob.objects.filter(
            state__in=[SummaryBackfillJob.State.RUNNING, SummaryBackfillJob.State.PAUSED],
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
            else self._start_of_current_month()
        )
        if range_start >= range_end:
            raise CommandError('--from must be before --to')

        SummaryBackfillJob.objects.create(
            cursor=range_end,
            range_start=range_start,
            range_end=range_end,
        )
        self.stdout.write(self.style.SUCCESS(
            f'Started backfill job: {range_start:%Y-%m-%d} → {range_end:%Y-%m-%d}'
        ))

    def _status(self):
        job = SummaryBackfillJob.objects.order_by('-created').first()
        if job is None:
            self.stdout.write('No backfill job has been started.')
            return

        total_seconds = (job.range_end - job.range_start).total_seconds()
        done_seconds = (job.range_end - job.cursor).total_seconds()
        percent = 100 * done_seconds / total_seconds if total_seconds else 100

        self.stdout.write(f'State: {job.state}')
        self.stdout.write(f'Phase: {job.phase}')
        self.stdout.write(f'Cursor: {job.cursor:%Y-%m-%d}')
        self.stdout.write(f'Range: {job.range_start:%Y-%m-%d} → {job.range_end:%Y-%m-%d}')
        self.stdout.write(f'Progress: {percent:.1f}%')
        if job.last_error:
            self.stdout.write(self.style.WARNING(f'Last error: {job.last_error}'))

    def _cancel(self):
        job = SummaryBackfillJob.objects.filter(
            state__in=[SummaryBackfillJob.State.RUNNING, SummaryBackfillJob.State.PAUSED],
        ).first()
        if job is None:
            self.stdout.write('No active backfill job to cancel.')
            return
        job.state = SummaryBackfillJob.State.DONE
        job.save(update_fields=['state'])
        self.stdout.write(self.style.SUCCESS('Backfill job cancelled.'))

    def _parse_date(self, value):
        d = parse_date(value)
        if d is None:
            raise CommandError(f'Invalid date: {value!r}. Use YYYY-MM-DD.')
        return make_aware(datetime(d.year, d.month, d.day), settings.DEFAULT_TIMEZONE)

    def _start_of_current_month(self):
        today = timezone.localtime(timezone.now(), settings.DEFAULT_TIMEZONE).date()
        return make_aware(datetime(today.year, today.month, 1), settings.DEFAULT_TIMEZONE)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose run --rm test pytest camp/apps/summaries/test_backfill.py::BackfillSummariesCommandTests -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add camp/apps/summaries/management/commands/backfill_summaries.py camp/apps/summaries/test_backfill.py
git commit -m "feat(summaries): add backfill_summaries start/status/cancel command"
```

---

### Task 7: `backfill_monitor_chunk` and `backfill_region_chunk` Huey tasks

**Files:**
- Modify: `camp/apps/summaries/tasks.py`
- Test: `camp/apps/summaries/test_backfill.py`

**Interfaces:**
- Consumes: `backfill_monitor_hours`, `backfill_region_hours`, `hour_range` from `camp.apps.summaries.backfill` (Tasks 1–2); `SummaryBackfillJob` (Task 4); `get_summarizable_entry_models` (already in `tasks.py`).
- Produces: `backfill_monitor_chunk(job_id, monitor_id, chunk_start, chunk_end, batch_id)`, `backfill_region_chunk(job_id, region_id, chunk_start, chunk_end, batch_id)`. Both are `@db_task(priority=1, queue='summaries')`. Each does its computation, then a **fenced** decrement of `pending_tasks` — only applied if `batch_id` and `phase` still match the job row.

- [ ] **Step 1: Write the failing tests**

```python
# Append to camp/apps/summaries/test_backfill.py
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from camp.apps.entries.models import PM25
from camp.apps.monitors.purpleair.models import PurpleAir
from camp.apps.regions.models import Region
from camp.apps.summaries.models import MonitorSummary, RegionSummary, SummaryBackfillJob
from camp.apps.summaries.tasks import backfill_monitor_chunk, backfill_region_chunk


class BackfillMonitorChunkTaskTests(TestCase):
    fixtures = ['purple-air.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.first()
        now = timezone.now()
        self.chunk_start = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=2)
        self.chunk_end = self.chunk_start + timedelta(hours=1)
        self.job = SummaryBackfillJob.objects.create(
            cursor=self.chunk_end, range_start=self.chunk_start - timedelta(days=1), range_end=self.chunk_end,
            phase=SummaryBackfillJob.Phase.MONITORS, pending_tasks=1, batch_id=1,
        )
        PM25.objects.create(
            monitor=self.monitor, timestamp=self.chunk_start + timedelta(minutes=5),
            stage=PM25.Stage.RAW, processor='', value=10.0, location=self.monitor.location,
        )

    def test_creates_summary_and_decrements_pending_tasks(self):
        backfill_monitor_chunk(self.job.pk, str(self.monitor.pk), self.chunk_start, self.chunk_end, 1)
        assert MonitorSummary.objects.filter(monitor=self.monitor).exists()
        self.job.refresh_from_db()
        assert self.job.pending_tasks == 0

    def test_stale_batch_id_does_not_decrement(self):
        backfill_monitor_chunk(self.job.pk, str(self.monitor.pk), self.chunk_start, self.chunk_end, 999)
        # Summary is still written — computation isn't fenced, only the counter is.
        assert MonitorSummary.objects.filter(monitor=self.monitor).exists()
        self.job.refresh_from_db()
        assert self.job.pending_tasks == 1

    def test_wrong_phase_does_not_decrement(self):
        self.job.phase = SummaryBackfillJob.Phase.REGIONS
        self.job.save(update_fields=['phase'])
        backfill_monitor_chunk(self.job.pk, str(self.monitor.pk), self.chunk_start, self.chunk_end, 1)
        self.job.refresh_from_db()
        assert self.job.pending_tasks == 1


class BackfillRegionChunkTaskTests(TestCase):
    fixtures = ['purple-air.yaml', 'regions.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.first()
        self.region = Region.objects.filter(boundary__isnull=False).first()
        if not self.region:
            self.skipTest('no region with boundary in fixtures')
        self.monitor.position = self.region.boundary.geometry.centroid
        self.monitor.save()

        self.hour = timezone.now().replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
        MonitorSummary.objects.create(
            monitor=self.monitor, timestamp=self.hour,
            resolution=MonitorSummary.Resolution.HOURLY, entry_type='pm25', processor='',
            count=10, expected_count=30, sum_value=200.0, sum_of_squares=4000.0,
            minimum=20.0, maximum=20.0, mean=20.0, stddev=0.0, p25=20.0, p75=20.0,
            tdigest={'C': [[20.0, 10]], 'n': 10}, is_complete=False,
        )

        self.job = SummaryBackfillJob.objects.create(
            cursor=self.hour + timedelta(hours=1), range_start=self.hour - timedelta(days=1),
            range_end=self.hour + timedelta(hours=1),
            phase=SummaryBackfillJob.Phase.REGIONS, pending_tasks=1, batch_id=1,
        )

    def test_creates_region_summary_and_decrements_pending_tasks(self):
        backfill_region_chunk(self.job.pk, str(self.region.pk), self.hour, self.hour + timedelta(hours=1), 1)
        assert RegionSummary.objects.filter(region=self.region).exists()
        self.job.refresh_from_db()
        assert self.job.pending_tasks == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose run --rm test pytest camp/apps/summaries/test_backfill.py::BackfillMonitorChunkTaskTests camp/apps/summaries/test_backfill.py::BackfillRegionChunkTaskTests -v`
Expected: FAIL with `ImportError: cannot import name 'backfill_monitor_chunk'`

- [ ] **Step 3: Add the tasks**

In `camp/apps/summaries/tasks.py`, update the imports at the top of the file — add `F` to the existing `django.db.models` import and add a new import from `backfill`:

```python
from django.db.models import Exists, F, OuterRef, Q
```

```python
from camp.apps.summaries.backfill import backfill_monitor_hours, backfill_region_hours, hour_range
from camp.apps.summaries.models import BaseSummary, MonitorSummary, RegionSummary, SummaryBackfillJob
```

(this replaces the existing `from camp.apps.summaries.models import BaseSummary, MonitorSummary, RegionSummary` line)

Then append to `camp/apps/summaries/tasks.py`:

```python
# ---- Backfill ----

@db_task(priority=1, queue='summaries')
def backfill_monitor_chunk(job_id, monitor_id, chunk_start, chunk_end, batch_id):
    """Compute one monitor's hourly summaries for a backfill chunk, then report completion."""
    monitor = Monitor.objects.get(pk=monitor_id)
    entry_models = get_summarizable_entry_models()
    backfill_monitor_hours(monitor, chunk_start, chunk_end, entry_models)

    SummaryBackfillJob.objects.filter(
        pk=job_id, batch_id=batch_id, phase=SummaryBackfillJob.Phase.MONITORS,
    ).update(pending_tasks=F('pending_tasks') - 1)


@db_task(priority=1, queue='summaries')
def backfill_region_chunk(job_id, region_id, chunk_start, chunk_end, batch_id):
    """Compute one region's hourly summaries for a backfill chunk, then report completion."""
    region = Region.objects.select_related('boundary').get(pk=region_id)
    monitor_grades = dict(region.monitors.with_grade().values_list('pk', 'grade'))
    hours = list(hour_range(chunk_start, chunk_end))
    backfill_region_hours(region, hours, monitor_grades)

    SummaryBackfillJob.objects.filter(
        pk=job_id, batch_id=batch_id, phase=SummaryBackfillJob.Phase.REGIONS,
    ).update(pending_tasks=F('pending_tasks') - 1)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose run --rm test pytest camp/apps/summaries/test_backfill.py -v`
Expected: PASS (all tests so far)

- [ ] **Step 5: Commit**

```bash
git add camp/apps/summaries/tasks.py camp/apps/summaries/test_backfill.py
git commit -m "feat(summaries): add backfill_monitor_chunk and backfill_region_chunk tasks"
```

---

### Task 8: `backfill_summaries_tick` — claiming, dispatch, completion, and staleness recovery

**Files:**
- Modify: `camp/apps/summaries/tasks.py`
- Test: `camp/apps/summaries/test_backfill.py`

**Interfaces:**
- Consumes: `chunk_start_for`, `iter_chunk_days`, `daily_rollup_window`, `higher_rollup_windows`, `monitors_with_data_in`, `regions_with_monitors` (Tasks 1–2); `backfill_monitor_chunk`, `backfill_region_chunk` (Task 7); `rollup_monitor_summaries`, `rollup_region_summaries` (already in `tasks.py`).
- Produces: `backfill_summaries_tick()` — `@db_periodic_task(crontab(minute='*'), priority=1, queue='summaries')`.

This is the full state machine from the spec, built as one function with four private helpers (`_backfill_dispatch_monitors`, `_backfill_dispatch_regions`, `_backfill_complete_chunk`, `_backfill_restart_batch`). All tests construct the job directly in whichever `phase` they want to exercise — the state machine doesn't need to be driven from `idle` to test a later transition.

- [ ] **Step 1: Write the failing tests**

```python
# Append to camp/apps/summaries/test_backfill.py
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.utils import timezone

from camp.apps.entries.models import PM25
from camp.apps.monitors.purpleair.models import PurpleAir
from camp.apps.summaries.models import BaseSummary, MonitorSummary, SummaryBackfillJob
from camp.apps.summaries.tasks import backfill_summaries_tick


class BackfillSummariesTickClaimingTests(TestCase):
    def _make_job(self, **kwargs):
        now = timezone.now().replace(minute=0, second=0, microsecond=0)
        defaults = dict(cursor=now, range_start=now - timedelta(days=30), range_end=now)
        defaults.update(kwargs)
        return SummaryBackfillJob.objects.create(**defaults)

    def test_does_nothing_when_no_running_job(self):
        self._make_job(state=SummaryBackfillJob.State.DONE)
        backfill_summaries_tick()
        # No exception, and the DONE job is untouched.
        job = SummaryBackfillJob.objects.get()
        assert job.state == SummaryBackfillJob.State.DONE

    def test_skips_job_with_recent_lock(self):
        job = self._make_job(locked_at=timezone.now())
        with self.captureOnCommitCallbacks(execute=True):
            backfill_summaries_tick()
        job.refresh_from_db()
        # Still idle/batch_id 0 — the tick declined to claim a freshly-locked job.
        assert job.batch_id == 0

    def test_claims_job_with_stale_lock(self):
        job = self._make_job(locked_at=timezone.now() - timedelta(minutes=5))
        with self.captureOnCommitCallbacks(execute=True):
            backfill_summaries_tick()
        job.refresh_from_db()
        assert job.batch_id == 1


class BackfillSummariesTickDispatchMonitorsTests(TestCase):
    fixtures = ['purple-air.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.first()
        now = timezone.now().replace(minute=0, second=0, microsecond=0)
        self.job = SummaryBackfillJob.objects.create(
            cursor=now, range_start=now - timedelta(days=30), range_end=now,
        )

    def test_idle_job_with_data_dispatches_monitor_batch(self):
        PM25.objects.create(
            monitor=self.monitor, timestamp=self.job.cursor - timedelta(hours=1, minutes=-5),
            stage=PM25.Stage.RAW, processor='', value=10.0, location=self.monitor.location,
        )
        with self.captureOnCommitCallbacks(execute=True):
            backfill_summaries_tick()

        # The dispatched backfill_monitor_chunk task ran synchronously (immediate=True)
        # and decremented pending_tasks back to 0, then the tick's own transaction
        # already moved on — check the job ended up in the monitors phase with the
        # batch drained.
        self.job.refresh_from_db()
        assert self.job.phase == SummaryBackfillJob.Phase.MONITORS
        assert self.job.pending_tasks == 0
        assert self.job.batch_id == 1
        assert MonitorSummary.objects.filter(monitor=self.monitor).exists()

    def test_idle_job_with_no_data_dispatches_empty_batch(self):
        with self.captureOnCommitCallbacks(execute=True):
            backfill_summaries_tick()
        self.job.refresh_from_db()
        assert self.job.phase == SummaryBackfillJob.Phase.MONITORS
        assert self.job.pending_tasks == 0
        assert self.job.batch_id == 1


class BackfillSummariesTickDispatchRegionsTests(TestCase):
    fixtures = ['purple-air.yaml', 'regions.yaml']

    def setUp(self):
        from camp.apps.regions.models import Region
        self.region = Region.objects.filter(boundary__isnull=False).first()
        if not self.region:
            self.skipTest('no region with boundary in fixtures')
        monitor = PurpleAir.objects.first()
        monitor.position = self.region.boundary.geometry.centroid
        monitor.save()

        now = timezone.now().replace(minute=0, second=0, microsecond=0)
        self.job = SummaryBackfillJob.objects.create(
            cursor=now, chunk_start=now - timedelta(days=7),
            range_start=now - timedelta(days=30), range_end=now,
            phase=SummaryBackfillJob.Phase.MONITORS, pending_tasks=0, batch_id=1,
        )

    def test_monitors_drained_dispatches_region_batch(self):
        with self.captureOnCommitCallbacks(execute=True):
            backfill_summaries_tick()
        self.job.refresh_from_db()
        assert self.job.phase == SummaryBackfillJob.Phase.REGIONS
        assert self.job.batch_id == 2

    def test_monitors_still_pending_does_nothing(self):
        self.job.pending_tasks = 3
        self.job.phase_started_at = timezone.now()
        self.job.save()
        backfill_summaries_tick()
        self.job.refresh_from_db()
        assert self.job.phase == SummaryBackfillJob.Phase.MONITORS
        assert self.job.pending_tasks == 3
        assert self.job.batch_id == 1


class BackfillSummariesTickCompleteChunkTests(TestCase):
    def setUp(self):
        # Chunk whose chunk_start lands exactly on a month start (Jul 1,
        # 2023), so completing it exercises both the daily and the
        # higher-rollup cascade (July is a quarter-start month) in one call.
        self.month_start = _day(2023, 7, 1)
        self.job = SummaryBackfillJob.objects.create(
            cursor=self.month_start + timedelta(days=2),
            chunk_start=self.month_start,
            range_start=self.month_start - timedelta(days=365),
            range_end=self.month_start + timedelta(days=2),
            phase=SummaryBackfillJob.Phase.REGIONS, pending_tasks=0, batch_id=1,
        )

    def test_regions_drained_advances_cursor_to_chunk_start(self):
        backfill_summaries_tick()
        self.job.refresh_from_db()
        assert self.job.cursor == self.month_start
        assert self.job.phase == SummaryBackfillJob.Phase.IDLE
        assert self.job.chunk_start is None

    def test_regions_drained_resets_failure_count(self):
        self.job.consecutive_failures = 2
        self.job.last_error = 'boom'
        self.job.save()
        backfill_summaries_tick()
        self.job.refresh_from_db()
        assert self.job.consecutive_failures == 0
        assert self.job.last_error == ''

    def test_reaching_range_start_marks_job_done(self):
        self.job.range_start = self.month_start
        self.job.save()
        backfill_summaries_tick()
        self.job.refresh_from_db()
        assert self.job.state == SummaryBackfillJob.State.DONE

    def test_july_first_cascades_monthly_and_quarterly_rollups(self):
        # July is a quarter-start month (Jul/Aug/Sep = Q3) — crossing Jul 1
        # while walking backward should trigger a monthly AND a quarterly
        # rollup call, on top of the daily rollups for each day in the
        # chunk. Rollup *correctness* (the actual aggregated values) is
        # already covered by RollupMonitorSummariesTests /
        # RollupRegionSummariesTests in tests.py — this only proves the
        # cascade invokes the right windows.
        with patch('camp.apps.summaries.tasks.rollup_monitor_summaries') as mock_rollup:
            backfill_summaries_tick()

        resolutions_called = [call.args[0] for call in mock_rollup.call_args_list]
        assert BaseSummary.Resolution.DAILY in resolutions_called
        assert BaseSummary.Resolution.MONTHLY in resolutions_called
        assert BaseSummary.Resolution.QUARTERLY in resolutions_called
        assert BaseSummary.Resolution.SEASONAL not in resolutions_called
        assert BaseSummary.Resolution.YEARLY not in resolutions_called

        monthly_call = next(c for c in mock_rollup.call_args_list if c.args[0] == BaseSummary.Resolution.MONTHLY)
        assert monthly_call.args[2] == self.month_start  # window_start


class BackfillSummariesTickStalenessRecoveryTests(TestCase):
    def setUp(self):
        now = timezone.now().replace(minute=0, second=0, microsecond=0)
        self.job = SummaryBackfillJob.objects.create(
            cursor=now, chunk_start=now - timedelta(days=7),
            range_start=now - timedelta(days=30), range_end=now,
            phase=SummaryBackfillJob.Phase.MONITORS, pending_tasks=5, batch_id=1,
        )

    def test_fresh_batch_is_left_alone(self):
        self.job.phase_started_at = timezone.now()
        self.job.save()
        backfill_summaries_tick()
        self.job.refresh_from_db()
        assert self.job.pending_tasks == 5
        assert self.job.phase == SummaryBackfillJob.Phase.MONITORS

    def test_stale_batch_resets_to_idle_for_redispatch(self):
        self.job.phase_started_at = timezone.now() - timedelta(minutes=31)
        self.job.save()
        backfill_summaries_tick()
        self.job.refresh_from_db()
        assert self.job.phase == SummaryBackfillJob.Phase.IDLE
        assert self.job.pending_tasks == 0
        assert self.job.consecutive_failures == 1
        assert 'stalled' in self.job.last_error

    def test_five_consecutive_stalls_marks_job_failed(self):
        self.job.phase_started_at = timezone.now() - timedelta(minutes=31)
        self.job.consecutive_failures = 4
        self.job.save()
        backfill_summaries_tick()
        self.job.refresh_from_db()
        assert self.job.state == SummaryBackfillJob.State.FAILED
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `docker compose run --rm test pytest camp/apps/summaries/test_backfill.py -v -k BackfillSummariesTick`
Expected: FAIL with `ImportError: cannot import name 'backfill_summaries_tick'`

- [ ] **Step 3: Write the orchestrator**

Append to `camp/apps/summaries/tasks.py` (after the `backfill_region_chunk` task from Task 7). This also needs `chunk_start_for`, `iter_chunk_days`, `daily_rollup_window`, `higher_rollup_windows`, `monitors_with_data_in`, `regions_with_monitors` — add them to the existing `from camp.apps.summaries.backfill import ...` line so it reads:

```python
from camp.apps.summaries.backfill import (
    backfill_monitor_hours,
    backfill_region_hours,
    chunk_start_for,
    daily_rollup_window,
    higher_rollup_windows,
    hour_range,
    iter_chunk_days,
    monitors_with_data_in,
    regions_with_monitors,
)
```

Also add these imports at the top of `tasks.py`:

```python
from django.db import transaction
```

Then append:

```python
# ---- Backfill orchestrator ----

BACKFILL_LOCK_STALE_SECONDS = 30
BACKFILL_BATCH_STALE_MINUTES = 30
BACKFILL_MAX_CONSECUTIVE_FAILURES = 5


@db_periodic_task(crontab(minute='*'), priority=1, queue='summaries')
def backfill_summaries_tick():
    """
    Drive one step of the active SummaryBackfillJob, if any. Never blocks on
    the sub-tasks it dispatches — it only checks whether the current phase's
    batch has drained (pending_tasks == 0) and, if so, advances to the next
    phase. See docs/superpowers/specs/2026-07-13-summary-backfill-design.md.
    """
    now = timezone.now()

    with transaction.atomic():
        job = (
            SummaryBackfillJob.objects
            .select_for_update(skip_locked=True)
            .filter(state=SummaryBackfillJob.State.RUNNING)
            .filter(
                Q(locked_at__isnull=True) |
                Q(locked_at__lt=now - timedelta(seconds=BACKFILL_LOCK_STALE_SECONDS))
            )
            .order_by('created')
            .first()
        )
        if job is None:
            return

        job.locked_at = now
        job.save(update_fields=['locked_at'])

        if job.phase != SummaryBackfillJob.Phase.IDLE and job.pending_tasks > 0:
            stale_before = now - timedelta(minutes=BACKFILL_BATCH_STALE_MINUTES)
            if job.phase_started_at and job.phase_started_at < stale_before:
                _backfill_restart_batch(job)
            return

        if job.phase == SummaryBackfillJob.Phase.IDLE:
            _backfill_dispatch_monitors(job)
        elif job.phase == SummaryBackfillJob.Phase.MONITORS:
            _backfill_dispatch_regions(job)
        elif job.phase == SummaryBackfillJob.Phase.REGIONS:
            _backfill_complete_chunk(job)


def _backfill_dispatch_monitors(job):
    chunk_start = chunk_start_for(job.cursor, job.range_start)
    entry_models = get_summarizable_entry_models()
    monitor_ids = monitors_with_data_in(chunk_start, job.cursor, entry_models)

    job.chunk_start = chunk_start
    job.batch_id += 1
    job.pending_tasks = len(monitor_ids)
    job.phase = SummaryBackfillJob.Phase.MONITORS
    job.phase_started_at = timezone.now()
    job.save()

    batch_id = job.batch_id
    chunk_end = job.cursor
    for monitor_id in monitor_ids:
        transaction.on_commit(
            lambda m=monitor_id: backfill_monitor_chunk(job.pk, str(m), chunk_start, chunk_end, batch_id)
        )


def _backfill_dispatch_regions(job):
    region_ids = regions_with_monitors()

    job.batch_id += 1
    job.pending_tasks = len(region_ids)
    job.phase = SummaryBackfillJob.Phase.REGIONS
    job.phase_started_at = timezone.now()
    job.save()

    batch_id = job.batch_id
    chunk_start = job.chunk_start
    chunk_end = job.cursor
    for region_id in region_ids:
        transaction.on_commit(
            lambda r=region_id: backfill_region_chunk(job.pk, str(r), chunk_start, chunk_end, batch_id)
        )


def _backfill_complete_chunk(job):
    for day in iter_chunk_days(job.chunk_start, job.cursor):
        target, source, window_start, window_end = daily_rollup_window(day)
        rollup_monitor_summaries(target, source, window_start, window_end)
        rollup_region_summaries(target, source, window_start, window_end)

        for target, source, window_start, window_end in higher_rollup_windows(day):
            rollup_monitor_summaries(target, source, window_start, window_end)
            rollup_region_summaries(target, source, window_start, window_end)

    job.cursor = job.chunk_start
    job.chunk_start = None
    job.phase = SummaryBackfillJob.Phase.IDLE
    job.pending_tasks = 0
    job.consecutive_failures = 0
    job.last_error = ''
    if job.cursor <= job.range_start:
        job.state = SummaryBackfillJob.State.DONE
    job.save()


def _backfill_restart_batch(job):
    job.consecutive_failures += 1
    job.last_error = (
        f'Batch {job.batch_id} stalled in phase "{job.phase}" with '
        f'{job.pending_tasks} pending task(s); restarting from the monitors phase.'
    )
    job.phase = SummaryBackfillJob.Phase.IDLE
    job.pending_tasks = 0
    if job.consecutive_failures >= BACKFILL_MAX_CONSECUTIVE_FAILURES:
        job.state = SummaryBackfillJob.State.FAILED
    job.save()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `docker compose run --rm test pytest camp/apps/summaries/test_backfill.py -v`
Expected: PASS (all tests in the file)

- [ ] **Step 5: Run the full summaries suite as a regression check**

Run: `docker compose run --rm test pytest camp/apps/summaries/ -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add camp/apps/summaries/tasks.py camp/apps/summaries/test_backfill.py
git commit -m "feat(summaries): add backfill_summaries_tick orchestrator"
```

---

## Self-Review

**1. Spec coverage:**
- Non-blocking orchestrator, `phase`/`pending_tasks` state machine → Task 8.
- Fan-out per monitor, then per region, in that order → Task 8 (`_backfill_dispatch_monitors`/`_backfill_dispatch_regions`), gated by phase order.
- `batch_id` fencing → Task 7 (fenced decrement) + Task 8 (`batch_id` bump on every dispatch, including restarts).
- `transaction.on_commit` dispatch safety → Task 8.
- Rollup cascade via boundary-crossing detection → Task 1 (pure logic) + Task 8 (`_backfill_complete_chunk` invocation).
- `cursor`/`chunk_start` timeline tracking → Task 4 (fields) + Task 8 (only `_backfill_complete_chunk` moves `cursor`).
- Staleness restart + `consecutive_failures`/`failed` → Task 8 (`_backfill_restart_batch`).
- Cancellation mid-batch → covered by the `state='running'` filter in `backfill_summaries_tick`'s claim query (Task 8) — no separate code path needed, matches the spec's reasoning that cancellation just needs the orchestrator to stop claiming the job.
- `backfill.py` code-reuse extraction → Tasks 1–3.
- Management command (`start`/`status`/`cancel`) → Task 6.
- Admin → Task 5.
- 1-minute tick / 30-second lock staleness / 30-minute batch staleness / 5-failure threshold → Task 8 constants.
- All items from the spec's "Out of scope" section are correctly left undone (no per-monitor progress tracking, no multiple concurrent jobs, no configurable chunk size, no per-sub-task retry policy).

**2. Placeholder scan:** No TBD/TODO markers, no vacuous assertions.

**3. Type consistency:** Checked signatures used across tasks:
- `backfill_monitor_hours(monitor, chunk_start, chunk_end, entry_models)` — defined in Task 2, called identically in Task 3 (`rebuild_summaries.py`) and Task 7 (`backfill_monitor_chunk`).
- `backfill_region_hours(region, hours, monitor_grades)` — defined in Task 2, called identically in Task 3 and Task 7.
- `chunk_start_for(cursor, range_start)`, `iter_chunk_days(chunk_start, chunk_end)`, `daily_rollup_window(day)`, `higher_rollup_windows(day)` — defined in Task 1, called identically in Task 8.
- `monitors_with_data_in(chunk_start, chunk_end, entry_models)`, `regions_with_monitors()` — defined in Task 2, called identically in Task 8.
- `SummaryBackfillJob.State`/`SummaryBackfillJob.Phase` choices — defined in Task 4, used identically (string values `running`/`paused`/`done`/`failed` and `idle`/`monitors`/`regions`) across Tasks 6, 7, 8.
- Monitor/region ids are passed to `backfill_monitor_chunk`/`backfill_region_chunk` as `str(...)` in Task 8's dispatch helpers, matching the `str(monitor_id)` convention already used by `summarize_monitor_hour`/`summarize_region_hour` elsewhere in `tasks.py`.

No gaps found beyond the one noted above (already addressed with an inline comment, not a functional gap).

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-13-summary-backfill.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
