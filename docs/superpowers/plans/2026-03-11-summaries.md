# Summaries Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a system that computes and stores statistical summaries (hourly through yearly) for monitor and region air quality data.

**Architecture:** Hourly Huey tasks query raw entries to produce `MonitorSummary` records per monitor/entry-type/stage/processor combo; a follow-up task aggregates those into `RegionSummary` records with FEM/LCS health weighting. Daily through yearly summaries roll up from the level below via separate periodic tasks, never re-reading raw entries.

**Tech Stack:** Django 4.2, Huey (django-huey), PostGIS, NumPy, `tdigest` (to be added)

---

## Chunk 1: Foundation

### Task 1: Register app and add tdigest dependency

**Files:**
- Modify: `requirements/base.txt`
- Modify: `camp/settings/base.py`
- Modify: `camp/apps/summaries/apps.py`

- [ ] **Step 1: Add tdigest to requirements**

  In `requirements/base.txt`, after the `tqdm` line add:
  ```
  tdigest==0.5.2.2
  ```

- [ ] **Step 2: Rebuild the Docker images to install the package**

  Run: `docker compose build web test`

- [ ] **Step 3: Verify tdigest imports correctly**

  Run: `docker compose run --rm web python -c "from tdigest import TDigest; d = TDigest(); d.update(1.0); print(d.percentile(50))"`
  Expected: prints a float (≈1.0)

- [ ] **Step 4: Register the app in INSTALLED_APPS**

  In `camp/settings/base.py`, add `'camp.apps.summaries'` to the `INSTALLED_APPS` list alongside the other `camp.apps.*` entries.

- [ ] **Step 5: Fix apps.py**

  Replace the entire contents of `camp/apps/summaries/apps.py` with:

  ```python
  from django.apps import AppConfig


  class SummariesConfig(AppConfig):
      name = 'camp.apps.summaries'
  ```

  The `default_auto_field` line was removed. While it has no practical effect (all models set `primary_key=True` explicitly via `SmallUUIDField`), removing it avoids confusion and aligns with the rest of the project.

- [ ] **Step 6: Verify app loads**

  Run: `docker compose run --rm web python manage.py check`
  Expected: System check identified no issues.

- [ ] **Step 7: Commit**

  ```bash
  git add requirements/base.txt camp/settings/base.py camp/apps/summaries/apps.py
  git commit -m "Add summaries app to INSTALLED_APPS, add tdigest dependency"
  ```

---

### Task 2: Generate migration

**Files:**
- Create: `camp/apps/summaries/migrations/0001_initial.py` (generated)

> Note: `camp/apps/summaries/models.py` is pre-authored and already in the repo — no changes needed to it in this task.

- [ ] **Step 1: Generate the migration**

  Run: `docker compose run --rm web python manage.py makemigrations summaries`
  Expected: `Migrations for 'summaries': camp/apps/summaries/migrations/0001_initial.py`

- [ ] **Step 2: Apply the migration**

  Run: `docker compose run --rm web python manage.py migrate summaries`
  Expected: `Applying summaries.0001_initial... OK`

- [ ] **Step 3: Verify tables exist**

  Run: `docker compose run --rm web python manage.py dbshell -- -c "SELECT tablename FROM pg_tables WHERE tablename LIKE 'summaries_%';"`
  Expected: rows for `summaries_monitorsummary` and `summaries_regionsummary`.

- [ ] **Step 4: Commit**

  ```bash
  git add camp/apps/summaries/migrations/
  git commit -m "Add initial summaries migration"
  ```

---

## Chunk 2: Aggregation Logic

All computation lives in `camp/apps/summaries/aggregators.py`. Three public functions:

- `compute_monitor_summary(monitor, timestamp, EntryModel, stage, processor)` → stats dict or None
- `rollup_summaries(queryset)` → stats dict or None
- `compute_region_summary(region, timestamp, entry_type, stage, processor)` → stats dict or None

A `get_monitor_weight(monitor, hour)` helper handles the FEM/LCS weighting.

### Task 3: TDigest utilities and compute_monitor_summary

**Files:**
- Create: `camp/apps/summaries/aggregators.py`
- Modify: `camp/apps/summaries/tests.py`

- [ ] **Step 1: Write the failing test**

  Replace `camp/apps/summaries/tests.py` with:

  ```python
  from datetime import timedelta

  import pytest

  from django.test import TestCase
  from django.utils import timezone

  from camp.apps.entries.models import PM25
  from camp.apps.monitors.models import Monitor
  from camp.apps.summaries.aggregators import compute_monitor_summary
  from camp.apps.summaries.models import MonitorSummary


  class ComputeMonitorSummaryTests(TestCase):
      fixtures = ['purple-air.yaml']

      def setUp(self):
          self.monitor = Monitor.objects.first()
          self.hour = timezone.now().replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)

      def _make_entry(self, value, offset_minutes=0):
          return PM25.objects.create(
              monitor=self.monitor,
              timestamp=self.hour + timedelta(minutes=offset_minutes),
              stage=PM25.Stage.RAW,
              processor='',
              value=value,
              location=self.monitor.location,
          )

      def test_returns_none_when_no_entries(self):
          result = compute_monitor_summary(
              self.monitor, self.hour, PM25, PM25.Stage.RAW, ''
          )
          self.assertIsNone(result)

      def test_computes_basic_stats(self):
          values = [10.0, 20.0, 30.0, 40.0, 50.0]
          for i, v in enumerate(values):
              self._make_entry(v, offset_minutes=i * 2)

          result = compute_monitor_summary(
              self.monitor, self.hour, PM25, PM25.Stage.RAW, ''
          )

          self.assertIsNotNone(result)
          self.assertEqual(result['count'], 5)
          self.assertAlmostEqual(result['mean'], 30.0)
          self.assertAlmostEqual(result['minimum'], 10.0)
          self.assertAlmostEqual(result['maximum'], 50.0)
          self.assertAlmostEqual(result['sum_value'], 150.0)
          self.assertIn('tdigest', result)
          self.assertIsInstance(result['tdigest'], dict)

      def test_is_complete_true_when_sufficient_coverage(self):
          # PurpleAir expects 30 readings/hour (2-min interval).
          # 80% of 30 = 24. Create 25 entries.
          for i in range(25):
              self._make_entry(15.0, offset_minutes=i * 2)

          result = compute_monitor_summary(
              self.monitor, self.hour, PM25, PM25.Stage.RAW, ''
          )
          self.assertTrue(result['is_complete'])

      def test_is_complete_false_when_insufficient_coverage(self):
          # Only 5 entries out of 30 expected
          for i in range(5):
              self._make_entry(15.0, offset_minutes=i * 2)

          result = compute_monitor_summary(
              self.monitor, self.hour, PM25, PM25.Stage.RAW, ''
          )
          self.assertFalse(result['is_complete'])

      def test_only_includes_entries_in_window(self):
          self._make_entry(100.0, offset_minutes=-5)   # before window
          self._make_entry(10.0, offset_minutes=5)     # in window
          self._make_entry(100.0, offset_minutes=65)   # after window

          result = compute_monitor_summary(
              self.monitor, self.hour, PM25, PM25.Stage.RAW, ''
          )
          self.assertEqual(result['count'], 1)
          self.assertAlmostEqual(result['mean'], 10.0)
  ```

- [ ] **Step 2: Run the test to verify it fails**

  Run: `docker compose run --rm test pytest camp/apps/summaries/tests.py -v`
  Expected: FAIL — `ImportError: cannot import name 'compute_monitor_summary'`

- [ ] **Step 3: Implement compute_monitor_summary**

  Create `camp/apps/summaries/aggregators.py`:

  ```python
  from datetime import timedelta

  import numpy as np
  from tdigest import TDigest


  # Weight constants for region summary weighting
  FEM_WEIGHT = 3.0
  LCS_WEIGHT = 1.0
  MAX_HEALTH_SCORE = 3


  def tdigest_to_dict(digest: TDigest) -> dict:
      """Serialize a TDigest to a JSON-safe dict."""
      return {
          'C': [[c.mean, c.count] for c in digest.C.values()],
          'n': digest.n,
      }


  def tdigest_from_dict(data: dict) -> TDigest:
      """Deserialize a TDigest from a dict produced by tdigest_to_dict."""
      d = TDigest()
      for mean, count in data.get('C', []):
          d.update(mean, count)
      return d


  def merge_tdigests(dicts: list) -> TDigest:
      """Merge a list of serialized TDigest dicts into one TDigest."""
      merged = TDigest()
      for d in dicts:
          merged = merged + tdigest_from_dict(d)
      return merged


  def compute_monitor_summary(monitor, timestamp, EntryModel, stage, processor):
      """
      Compute summary stats for one monitor over one hour from raw entries.

      Returns a dict ready to use as MonitorSummary field values, or None if
      there are no entries in the window.
      """
      hour_end = timestamp + timedelta(hours=1)

      values = [
          float(v)
          for v in EntryModel.objects.filter(
              monitor=monitor,
              timestamp__gte=timestamp,
              timestamp__lt=hour_end,
              stage=stage,
              processor=processor,
          ).values_list('value', flat=True)
          if v is not None
      ]

      if not values:
          return None

      arr = np.array(values)
      count = len(values)
      expected_count = monitor.expected_hourly_entries or 1
      sum_value = float(arr.sum())
      sum_of_squares = float((arr ** 2).sum())
      mean = float(arr.mean())
      stddev = float(arr.std())

      digest = TDigest()
      digest.batch_update(arr)

      return {
          'count': count,
          'expected_count': expected_count,
          'sum_value': sum_value,
          'sum_of_squares': sum_of_squares,
          'minimum': float(arr.min()),
          'maximum': float(arr.max()),
          'mean': mean,
          'stddev': stddev,
          'p25': float(np.percentile(arr, 25)),
          'p75': float(np.percentile(arr, 75)),
          'tdigest': tdigest_to_dict(digest),
          'is_complete': count >= 0.8 * expected_count,
      }
  ```

- [ ] **Step 4: Run the tests to verify they pass**

  Run: `docker compose run --rm test pytest camp/apps/summaries/tests.py::ComputeMonitorSummaryTests -v`
  Expected: 5 passed

- [ ] **Step 5: Commit**

  ```bash
  git add camp/apps/summaries/aggregators.py camp/apps/summaries/tests.py
  git commit -m "Add compute_monitor_summary aggregator"
  ```

---

### Task 4: rollup_summaries

**Files:**
- Modify: `camp/apps/summaries/aggregators.py`
- Modify: `camp/apps/summaries/tests.py`

- [ ] **Step 1: Write the failing tests**

  Add to `camp/apps/summaries/tests.py`:

  ```python
  from camp.apps.summaries.aggregators import rollup_summaries


  class RollupSummariesTests(TestCase):
      fixtures = ['purple-air.yaml']

      def setUp(self):
          self.monitor = Monitor.objects.first()
          self.hour = timezone.now().replace(minute=0, second=0, microsecond=0) - timedelta(hours=2)

      def _make_monitor_summary(self, hour, mean, count=10, expected=30):
          arr = np.array([mean] * count)
          digest = TDigest()
          digest.batch_update(arr)
          return MonitorSummary.objects.create(
              monitor=self.monitor,
              timestamp=hour,
              resolution=MonitorSummary.Resolution.HOURLY,
              entry_type='pm25',
              stage='raw',
              processor='',
              count=count,
              expected_count=expected,
              sum_value=float(arr.sum()),
              sum_of_squares=float((arr ** 2).sum()),
              minimum=float(arr.min()),
              maximum=float(arr.max()),
              mean=float(arr.mean()),
              stddev=float(arr.std()),
              p25=float(np.percentile(arr, 25)),
              p75=float(np.percentile(arr, 75)),
              tdigest=tdigest_to_dict(digest),
              is_complete=count >= 0.8 * expected,
          )

      def test_returns_none_for_empty_queryset(self):
          result = rollup_summaries(MonitorSummary.objects.none())
          self.assertIsNone(result)

      def test_rolls_up_two_hours(self):
          self._make_monitor_summary(self.hour, mean=10.0, count=10)
          self._make_monitor_summary(self.hour + timedelta(hours=1), mean=20.0, count=10)

          qs = MonitorSummary.objects.filter(
              monitor=self.monitor,
              entry_type='pm25',
              stage='raw',
              processor='',
              resolution=MonitorSummary.Resolution.HOURLY,
          )
          result = rollup_summaries(qs)

          self.assertEqual(result['count'], 20)
          self.assertAlmostEqual(result['mean'], 15.0)
          self.assertAlmostEqual(result['minimum'], 10.0)
          self.assertAlmostEqual(result['maximum'], 20.0)
          self.assertIn('tdigest', result)

      def test_is_complete_aggregated_correctly(self):
          # 10 out of 30 expected = 33%, not complete
          self._make_monitor_summary(self.hour, mean=10.0, count=10, expected=30)
          self._make_monitor_summary(self.hour + timedelta(hours=1), mean=20.0, count=10, expected=30)

          qs = MonitorSummary.objects.filter(monitor=self.monitor)
          result = rollup_summaries(qs)

          # combined: 20 count, 60 expected = 33%, not complete
          self.assertFalse(result['is_complete'])
  ```

  Add to the top of test file imports: `import numpy as np`, `from tdigest import TDigest`, and `from camp.apps.summaries.aggregators import tdigest_to_dict`

- [ ] **Step 2: Run the test to verify it fails**

  Run: `docker compose run --rm test pytest camp/apps/summaries/tests.py::RollupSummariesTests -v`
  Expected: FAIL — `ImportError: cannot import name 'rollup_summaries'`

- [ ] **Step 3: Implement rollup_summaries**

  Add to `camp/apps/summaries/aggregators.py`:

  ```python
  def rollup_summaries(queryset):
      """
      Aggregate a queryset of MonitorSummary or RegionSummary records into one
      stats dict. Used to roll up hourly → daily → monthly etc.

      Returns None if the queryset is empty.
      """
      records = list(queryset.values(
          'count', 'expected_count', 'sum_value',
          'sum_of_squares', 'minimum', 'maximum', 'tdigest',
      ))

      if not records:
          return None

      count = sum(r['count'] for r in records)
      expected_count = sum(r['expected_count'] for r in records)
      sum_value = sum(r['sum_value'] for r in records)
      sum_of_squares = sum(r['sum_of_squares'] for r in records)
      minimum = min(r['minimum'] for r in records)
      maximum = max(r['maximum'] for r in records)

      mean = sum_value / count
      variance = max((sum_of_squares / count) - (mean ** 2), 0)
      stddev = variance ** 0.5

      merged = merge_tdigests([r['tdigest'] for r in records])

      return {
          'count': count,
          'expected_count': expected_count,
          'sum_value': sum_value,
          'sum_of_squares': sum_of_squares,
          'minimum': minimum,
          'maximum': maximum,
          'mean': mean,
          'stddev': stddev,
          'p25': merged.percentile(25),
          'p75': merged.percentile(75),
          'tdigest': tdigest_to_dict(merged),
          'is_complete': count >= 0.8 * expected_count,
      }
  ```

- [ ] **Step 4: Run the tests**

  Run: `docker compose run --rm test pytest camp/apps/summaries/tests.py::RollupSummariesTests -v`
  Expected: 3 passed

- [ ] **Step 5: Commit**

  ```bash
  git add camp/apps/summaries/aggregators.py camp/apps/summaries/tests.py
  git commit -m "Add rollup_summaries aggregator"
  ```

---

### Task 5: get_monitor_weight and compute_region_summary

**Files:**
- Modify: `camp/apps/summaries/aggregators.py`
- Modify: `camp/apps/summaries/tests.py`

- [ ] **Step 1: Write the failing tests**

  Add to `camp/apps/summaries/tests.py`:

  ```python
  from camp.apps.monitors.models import Monitor
  from camp.apps.qaqc.models import HealthCheck
  from camp.apps.regions.models import Region
  from camp.apps.summaries.aggregators import LCS_WEIGHT, get_monitor_weight, compute_region_summary
  from camp.apps.summaries.models import RegionSummary


  class GetMonitorWeightTests(TestCase):
      fixtures = ['purple-air.yaml', 'regions.yaml']

      def setUp(self):
          self.monitor = Monitor.objects.first()
          self.hour = timezone.now().replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)

      def test_lcs_monitor_without_health_check_gets_full_lcs_weight(self):
          # LCS monitor, no health check → type_weight × 1.0
          weight = get_monitor_weight(self.monitor, self.hour)
          self.assertEqual(weight, LCS_WEIGHT * 1.0)

      def test_lcs_monitor_with_zero_health_score_gets_zero_weight(self):
          HealthCheck.objects.create(monitor=self.monitor, hour=self.hour, score=0)
          weight = get_monitor_weight(self.monitor, self.hour)
          self.assertEqual(weight, 0.0)

      def test_lcs_monitor_with_max_health_score_gets_full_lcs_weight(self):
          HealthCheck.objects.create(monitor=self.monitor, hour=self.hour, score=3)
          weight = get_monitor_weight(self.monitor, self.hour)
          self.assertAlmostEqual(weight, LCS_WEIGHT * 1.0)


  class ComputeRegionSummaryTests(TestCase):
      fixtures = ['purple-air.yaml', 'regions.yaml']

      def setUp(self):
          self.monitor = Monitor.objects.first()
          self.hour = timezone.now().replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
          self.region = Region.objects.first()

      def _make_monitor_summary(self, mean=20.0, count=10):
          arr = np.array([mean] * count)
          digest = TDigest()
          digest.batch_update(arr)
          return MonitorSummary.objects.create(
              monitor=self.monitor,
              timestamp=self.hour,
              resolution=MonitorSummary.Resolution.HOURLY,
              entry_type='pm25',
              stage='raw',
              processor='',
              count=count,
              expected_count=30,
              sum_value=float(arr.sum()),
              sum_of_squares=float((arr ** 2).sum()),
              minimum=float(arr.min()),
              maximum=float(arr.max()),
              mean=float(arr.mean()),
              stddev=float(arr.std()),
              p25=float(np.percentile(arr, 25)),
              p75=float(np.percentile(arr, 75)),
              tdigest=tdigest_to_dict(digest),
              is_complete=count >= 24,
          )

      def test_returns_none_when_no_monitor_summaries(self):
          result = compute_region_summary(
              self.region, self.hour, 'pm25', 'raw', ''
          )
          self.assertIsNone(result)

      def test_returns_stats_when_monitor_in_region(self):
          # Place monitor inside the region's geometry (requires boundary to exist)
          self.skipTest('requires region with boundary') if not self.region.boundary else None
          self.monitor.position = self.region.boundary.geometry.centroid
          self.monitor.save()
          self._make_monitor_summary(mean=25.0)

          result = compute_region_summary(
              self.region, self.hour, 'pm25', 'raw', ''
          )

          self.assertIsNotNone(result)
          self.assertEqual(result['station_count'], 1)
          self.assertAlmostEqual(result['mean'], 25.0, places=1)

      def test_returns_none_for_region_without_boundary(self):
          # Region with no boundary should return None (no geometry to test against)
          region_no_boundary = Region.objects.filter(boundary__isnull=True).first()
          if region_no_boundary is None:
              self.skipTest('no region without boundary in fixtures')
          result = compute_region_summary(
              region_no_boundary, self.hour, 'pm25', 'raw', ''
          )
          self.assertIsNone(result)
  ```

  Note: `regions.yaml` fixture must have at least one region with a valid geometry. Verify with:
  `docker compose run --rm test python manage.py dumpdata regions.region --indent=2 | head -20`

- [ ] **Step 2: Run to verify failure**

  Run: `docker compose run --rm test pytest camp/apps/summaries/tests.py::GetMonitorWeightTests -v`
  Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement get_monitor_weight and compute_region_summary**

  Add to `camp/apps/summaries/aggregators.py`:

  ```python
  def get_monitor_weight(monitor, hour):
      """
      Return the contribution weight for a monitor at a given hour.

      FEM/FRM monitors always get FEM_WEIGHT (authoritative, no health check needed).
      LCS monitors get LCS_WEIGHT scaled by their health score (0–1 factor).
      Monitors with no health check record get health_factor=1.0.
      """
      from camp.apps.monitors.models import Monitor
      from camp.apps.qaqc.models import HealthCheck

      if monitor.grade in {Monitor.Grade.FEM, Monitor.Grade.FRM}:
          return FEM_WEIGHT

      try:
          health = HealthCheck.objects.get(monitor=monitor, hour=hour)
          health_factor = health.score / MAX_HEALTH_SCORE
      except HealthCheck.DoesNotExist:
          health_factor = 1.0

      return LCS_WEIGHT * health_factor


  def compute_region_summary(region, timestamp, entry_type, stage, processor):
      """
      Compute a weighted region summary from existing hourly MonitorSummary records.

      FEM monitors contribute at FEM_WEIGHT; LCS monitors are scaled by health score.
      Only monitors whose position falls within the region's geometry are included.

      Returns a dict ready to use as RegionSummary field values, or None if no
      contributing monitors have a summary for this window.
      """
      from camp.apps.monitors.models import Monitor
      from camp.apps.summaries.models import MonitorSummary, BaseSummary

      if not region.boundary:
          return None

      monitor_ids = list(
          Monitor.objects
          .filter(position__within=region.boundary.geometry)
          .values_list('pk', flat=True)
      )

      summaries = list(
          MonitorSummary.objects
          .filter(
              monitor_id__in=monitor_ids,
              timestamp=timestamp,
              resolution=BaseSummary.Resolution.HOURLY,
              entry_type=entry_type,
              stage=stage,
              processor=processor,
          )
          .select_related('monitor')
      )

      if not summaries:
          return None

      weighted_count = 0.0
      weighted_expected = 0.0
      weighted_sum = 0.0
      weighted_sum_sq = 0.0
      minimum = None
      maximum = None
      tdigests = []
      station_count = 0

      for s in summaries:
          weight = get_monitor_weight(s.monitor, timestamp)
          if weight == 0:
              continue

          weighted_count += weight * s.count
          weighted_expected += weight * s.expected_count
          weighted_sum += weight * s.sum_value
          weighted_sum_sq += weight * s.sum_of_squares
          minimum = s.minimum if minimum is None else min(minimum, s.minimum)
          maximum = s.maximum if maximum is None else max(maximum, s.maximum)
          tdigests.append(s.tdigest)
          station_count += 1

      if station_count == 0 or weighted_count == 0:
          return None

      mean = weighted_sum / weighted_count
      variance = max((weighted_sum_sq / weighted_count) - (mean ** 2), 0)
      stddev = variance ** 0.5
      merged = merge_tdigests(tdigests)

      return {
          'count': int(round(weighted_count)),
          'expected_count': int(round(weighted_expected)),
          'sum_value': weighted_sum,
          'sum_of_squares': weighted_sum_sq,
          'minimum': minimum,
          'maximum': maximum,
          'mean': mean,
          'stddev': stddev,
          'p25': merged.percentile(25),
          'p75': merged.percentile(75),
          'tdigest': tdigest_to_dict(merged),
          'is_complete': weighted_count >= 0.8 * weighted_expected,
          'station_count': station_count,
      }
  ```

- [ ] **Step 4: Run the tests**

  Run: `docker compose run --rm test pytest camp/apps/summaries/tests.py::GetMonitorWeightTests camp/apps/summaries/tests.py::ComputeRegionSummaryTests -v`
  Expected: all pass

- [ ] **Step 5: Run the full test suite for the app**

  Run: `docker compose run --rm test pytest camp/apps/summaries/tests.py -v`
  Expected: all pass

- [ ] **Step 6: Commit**

  ```bash
  git add camp/apps/summaries/aggregators.py camp/apps/summaries/tests.py
  git commit -m "Add get_monitor_weight and compute_region_summary aggregators"
  ```

---

## Chunk 3: Tasks

### Task 6: Hourly monitor summaries task

**Files:**
- Create: `camp/apps/summaries/tasks.py`
- Modify: `camp/apps/summaries/tests.py`

The task fans out one `summarize_monitor_hour` sub-task per (monitor, entry_type, stage, processor) combo that has entries in the target hour. Only entry models with a single `value` field are summarized (Particulates is skipped).

- [ ] **Step 1: Write the failing test**

  Add to `camp/apps/summaries/tests.py`:

  ```python
  from camp.apps.summaries.tasks import summarize_monitor_hour


  class SummarizeMonitorHourTests(TestCase):
      fixtures = ['purple-air.yaml']

      def setUp(self):
          self.monitor = Monitor.objects.first()
          self.hour = timezone.now().replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)

      def _make_entry(self, value, offset_minutes=0):
          return PM25.objects.create(
              monitor=self.monitor,
              timestamp=self.hour + timedelta(minutes=offset_minutes),
              stage=PM25.Stage.RAW,
              processor='',
              value=value,
              location=self.monitor.location,
          )

      def test_creates_monitor_summary(self):
          for i in range(5):
              self._make_entry(20.0 + i, offset_minutes=i * 2)

          summarize_monitor_hour(
              str(self.monitor.pk), self.hour, 'pm25', PM25.Stage.RAW, ''
          )

          self.assertEqual(MonitorSummary.objects.count(), 1)
          summary = MonitorSummary.objects.first()
          self.assertEqual(summary.monitor, self.monitor)
          self.assertEqual(summary.entry_type, 'pm25')
          self.assertEqual(summary.count, 5)

      def test_idempotent_when_called_twice(self):
          for i in range(5):
              self._make_entry(20.0, offset_minutes=i * 2)

          summarize_monitor_hour(
              str(self.monitor.pk), self.hour, 'pm25', PM25.Stage.RAW, ''
          )
          summarize_monitor_hour(
              str(self.monitor.pk), self.hour, 'pm25', PM25.Stage.RAW, ''
          )

          self.assertEqual(MonitorSummary.objects.count(), 1)

      def test_skips_when_no_entries(self):
          summarize_monitor_hour(
              str(self.monitor.pk), self.hour, 'pm25', PM25.Stage.RAW, ''
          )
          self.assertEqual(MonitorSummary.objects.count(), 0)
  ```

- [ ] **Step 2: Run to verify failure**

  Run: `docker compose run --rm test pytest camp/apps/summaries/tests.py::SummarizeMonitorHourTests -v`
  Expected: FAIL — `ImportError`

- [ ] **Step 3: Create tasks.py**

  Create `camp/apps/summaries/tasks.py`:

  ```python
  from datetime import timedelta

  from django.utils import timezone

  from django_huey import db_task, db_periodic_task
  from huey import crontab

  from camp.apps.monitors.models import Monitor


  def get_summarizable_entry_models():
      """Return entry models that have a single `value` field (excludes Particulates)."""
      from camp.apps.entries.utils import get_all_entry_models
      return [
          m for m in get_all_entry_models()
          if any(f.name == 'value' for f in m._meta.concrete_fields)
      ]


  @db_periodic_task(crontab(hour='*', minute='5'), priority=50)
  def hourly_monitor_summaries(hour=None):
      """
      Compute hourly MonitorSummary for every (monitor, entry_type, stage, processor)
      combo that has entries in the previous hour.
      """
      if hour is None:
          now = timezone.now().replace(minute=0, second=0, microsecond=0)
          hour = now - timedelta(hours=1)

      for EntryModel in get_summarizable_entry_models():
          combos = (
              EntryModel.objects
              .filter(
                  timestamp__gte=hour,
                  timestamp__lt=hour + timedelta(hours=1),
              )
              .values_list('monitor_id', 'stage', 'processor')
              .distinct()
          )
          for monitor_id, stage, processor in combos:
              summarize_monitor_hour(str(monitor_id), hour, EntryModel.entry_type, stage, processor)


  @db_task(priority=50)
  def summarize_monitor_hour(monitor_id, hour, entry_type, stage, processor):
      """Compute and save one hourly MonitorSummary record."""
      from camp.apps.entries.fields import EntryTypeField
      from camp.apps.summaries.aggregators import compute_monitor_summary
      from camp.apps.summaries.models import MonitorSummary, BaseSummary

      monitor = Monitor.objects.get(pk=monitor_id)
      EntryModel = EntryTypeField.get_model_map()[entry_type]

      stats = compute_monitor_summary(monitor, hour, EntryModel, stage, processor)
      if stats is None:
          return

      MonitorSummary.objects.update_or_create(
          monitor=monitor,
          timestamp=hour,
          resolution=BaseSummary.Resolution.HOURLY,
          entry_type=entry_type,
          stage=stage,
          processor=processor,
          defaults=stats,
      )
  ```

- [ ] **Step 4: Run the tests**

  Run: `docker compose run --rm test pytest camp/apps/summaries/tests.py::SummarizeMonitorHourTests -v`
  Expected: 3 passed

- [ ] **Step 5: Commit**

  ```bash
  git add camp/apps/summaries/tasks.py camp/apps/summaries/tests.py
  git commit -m "Add hourly monitor summary task"
  ```

---

### Task 7: Hourly region summaries task

**Files:**
- Modify: `camp/apps/summaries/tasks.py`
- Modify: `camp/apps/summaries/tests.py`

- [ ] **Step 1: Write the failing test**

  Add to `camp/apps/summaries/tests.py`:

  ```python
  from camp.apps.summaries.tasks import summarize_region_hour


  class SummarizeRegionHourTests(TestCase):
      fixtures = ['purple-air.yaml', 'regions.yaml']

      def setUp(self):
          self.monitor = Monitor.objects.first()
          self.hour = timezone.now().replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
          self.region = Region.objects.filter(boundary__isnull=False).first()
          if self.region is None:
              self.skipTest('no region with boundary in fixtures')
          # Place monitor inside region
          self.monitor.position = self.region.boundary.geometry.centroid
          self.monitor.save()

      def _make_monitor_summary(self, mean=20.0):
          arr = np.array([mean] * 10)
          digest = TDigest()
          digest.batch_update(arr)
          return MonitorSummary.objects.create(
              monitor=self.monitor,
              timestamp=self.hour,
              resolution=MonitorSummary.Resolution.HOURLY,
              entry_type='pm25',
              stage='raw',
              processor='',
              count=10,
              expected_count=30,
              sum_value=float(arr.sum()),
              sum_of_squares=float((arr ** 2).sum()),
              minimum=float(arr.min()),
              maximum=float(arr.max()),
              mean=float(arr.mean()),
              stddev=float(arr.std()),
              p25=float(np.percentile(arr, 25)),
              p75=float(np.percentile(arr, 75)),
              tdigest=tdigest_to_dict(digest),
              is_complete=False,
          )

      def test_creates_region_summary(self):
          self._make_monitor_summary(mean=25.0)

          summarize_region_hour(str(self.region.pk), self.hour, 'pm25', 'raw', '')

          self.assertEqual(RegionSummary.objects.count(), 1)
          summary = RegionSummary.objects.first()
          self.assertEqual(summary.region, self.region)
          self.assertEqual(summary.station_count, 1)

      def test_skips_when_no_monitor_summaries(self):
          summarize_region_hour(str(self.region.pk), self.hour, 'pm25', 'raw', '')
          self.assertEqual(RegionSummary.objects.count(), 0)

      def test_idempotent_when_called_twice(self):
          self._make_monitor_summary(mean=25.0)

          summarize_region_hour(str(self.region.pk), self.hour, 'pm25', 'raw', '')
          summarize_region_hour(str(self.region.pk), self.hour, 'pm25', 'raw', '')

          self.assertEqual(RegionSummary.objects.count(), 1)
  ```

- [ ] **Step 2: Run to verify failure**

  Run: `docker compose run --rm test pytest camp/apps/summaries/tests.py::SummarizeRegionHourTests -v`
  Expected: FAIL — `ImportError`

- [ ] **Step 3: Add region tasks to tasks.py**

  Add to `camp/apps/summaries/tasks.py`:

  ```python
  @db_periodic_task(crontab(hour='*', minute='15'), priority=50)
  def hourly_region_summaries(hour=None):
      """
      Compute hourly RegionSummary for each region, for each (entry_type, stage, processor)
      combo found in MonitorSummary records for that hour.
      """
      from camp.apps.regions.models import Region
      from camp.apps.summaries.models import MonitorSummary, BaseSummary

      if hour is None:
          now = timezone.now().replace(minute=0, second=0, microsecond=0)
          hour = now - timedelta(hours=1)

      combos = (
          MonitorSummary.objects
          .filter(timestamp=hour, resolution=BaseSummary.Resolution.HOURLY)
          .values_list('entry_type', 'stage', 'processor')
          .distinct()
      )

      for region in Region.objects.all():
          for entry_type, stage, processor in combos:
              summarize_region_hour(str(region.pk), hour, entry_type, stage, processor)


  @db_task(priority=50)
  def summarize_region_hour(region_id, hour, entry_type, stage, processor):
      """Compute and save one hourly RegionSummary record."""
      from camp.apps.regions.models import Region
      from camp.apps.summaries.aggregators import compute_region_summary
      from camp.apps.summaries.models import RegionSummary, BaseSummary

      region = Region.objects.get(pk=region_id)

      stats = compute_region_summary(region, hour, entry_type, stage, processor)
      if stats is None:
          return

      RegionSummary.objects.update_or_create(
          region=region,
          timestamp=hour,
          resolution=BaseSummary.Resolution.HOURLY,
          entry_type=entry_type,
          stage=stage,
          processor=processor,
          defaults=stats,
      )
  ```

- [ ] **Step 4: Run the tests**

  Run: `docker compose run --rm test pytest camp/apps/summaries/tests.py::SummarizeRegionHourTests -v`
  Expected: 3 passed

- [ ] **Step 5: Commit**

  ```bash
  git add camp/apps/summaries/tasks.py camp/apps/summaries/tests.py
  git commit -m "Add hourly region summary task"
  ```

---

### Task 8: Rollup tasks (daily through yearly)

**Files:**
- Modify: `camp/apps/summaries/tasks.py`
- Modify: `camp/apps/summaries/tests.py`

Rollup tasks share a common pattern: for a given period, find all lower-resolution summary records in that window and aggregate them up. The daily task runs at 00:15, monthly at 00:30 on the 1st, etc.

- [ ] **Step 1: Write the failing tests**

  Add to `camp/apps/summaries/tests.py`:

  ```python
  from camp.apps.summaries.tasks import rollup_monitor_summaries, rollup_region_summaries
  from camp.apps.summaries.models import RegionSummary


  class RollupMonitorSummariesTests(TestCase):
      fixtures = ['purple-air.yaml']

      def setUp(self):
          self.monitor = Monitor.objects.first()
          # Yesterday
          today = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
          self.yesterday = today - timedelta(days=1)

      def _make_hourly_summary(self, hour, mean=20.0):
          arr = np.array([mean] * 10)
          digest = TDigest()
          digest.batch_update(arr)
          return MonitorSummary.objects.create(
              monitor=self.monitor,
              timestamp=hour,
              resolution=MonitorSummary.Resolution.HOURLY,
              entry_type='pm25',
              stage='raw',
              processor='',
              count=10,
              expected_count=30,
              sum_value=float(arr.sum()),
              sum_of_squares=float((arr ** 2).sum()),
              minimum=float(arr.min()),
              maximum=float(arr.max()),
              mean=mean,
              stddev=0.0,
              p25=mean,
              p75=mean,
              tdigest=tdigest_to_dict(digest),
              is_complete=False,
          )

      def test_daily_rollup_aggregates_hourly_records(self):
          # Create 3 hourly records for yesterday
          for h in range(3):
              self._make_hourly_summary(self.yesterday + timedelta(hours=h), mean=10.0 * (h + 1))

          rollup_monitor_summaries(
              MonitorSummary.Resolution.DAILY,
              MonitorSummary.Resolution.HOURLY,
              self.yesterday,
              self.yesterday + timedelta(days=1),
          )

          daily = MonitorSummary.objects.filter(resolution=MonitorSummary.Resolution.DAILY)
          self.assertEqual(daily.count(), 1)
          self.assertAlmostEqual(daily.first().mean, 20.0)  # mean of (10, 20, 30)

      def test_daily_rollup_is_idempotent(self):
          for h in range(3):
              self._make_hourly_summary(self.yesterday + timedelta(hours=h))

          rollup_monitor_summaries(
              MonitorSummary.Resolution.DAILY,
              MonitorSummary.Resolution.HOURLY,
              self.yesterday,
              self.yesterday + timedelta(days=1),
          )
          rollup_monitor_summaries(
              MonitorSummary.Resolution.DAILY,
              MonitorSummary.Resolution.HOURLY,
              self.yesterday,
              self.yesterday + timedelta(days=1),
          )

          self.assertEqual(
              MonitorSummary.objects.filter(resolution=MonitorSummary.Resolution.DAILY).count(),
              1,
          )


  class RollupRegionSummariesTests(TestCase):
      fixtures = ['purple-air.yaml', 'regions.yaml']

      def setUp(self):
          self.region = Region.objects.filter(boundary__isnull=False).first()
          if self.region is None:
              self.skipTest('no region with boundary in fixtures')
          today = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
          self.yesterday = today - timedelta(days=1)

      def _make_hourly_region_summary(self, hour, mean=20.0, station_count=2):
          arr = np.array([mean] * 10)
          digest = TDigest()
          digest.batch_update(arr)
          return RegionSummary.objects.create(
              region=self.region,
              timestamp=hour,
              resolution=RegionSummary.Resolution.HOURLY,
              entry_type='pm25',
              stage='raw',
              processor='',
              count=10,
              expected_count=30,
              sum_value=float(arr.sum()),
              sum_of_squares=float((arr ** 2).sum()),
              minimum=float(arr.min()),
              maximum=float(arr.max()),
              mean=mean,
              stddev=0.0,
              p25=mean,
              p75=mean,
              tdigest=tdigest_to_dict(digest),
              is_complete=False,
              station_count=station_count,
          )

      def test_daily_rollup_aggregates_hourly_region_records(self):
          for h in range(3):
              self._make_hourly_region_summary(self.yesterday + timedelta(hours=h), mean=10.0 * (h + 1), station_count=h + 1)

          rollup_region_summaries(
              RegionSummary.Resolution.DAILY,
              RegionSummary.Resolution.HOURLY,
              self.yesterday,
              self.yesterday + timedelta(days=1),
          )

          daily = RegionSummary.objects.filter(resolution=RegionSummary.Resolution.DAILY)
          self.assertEqual(daily.count(), 1)
          self.assertAlmostEqual(daily.first().mean, 20.0)  # mean of (10, 20, 30)
          self.assertEqual(daily.first().station_count, 3)  # max of (1, 2, 3)
  ```

- [ ] **Step 2: Run to verify failure**

  Run: `docker compose run --rm test pytest camp/apps/summaries/tests.py::RollupMonitorSummariesTests -v`
  Expected: FAIL — `ImportError`

- [ ] **Step 3: Implement rollup tasks**

  Add `from django.db.models import Max` to the imports at the top of `camp/apps/summaries/tasks.py`.

  Add to `camp/apps/summaries/tasks.py`:

  ```python
  def rollup_monitor_summaries(target_resolution, source_resolution, window_start, window_end):
      """
      Roll up MonitorSummary records from source_resolution into target_resolution
      for the given time window.

      Finds all distinct (monitor, entry_type, stage, processor) combos in the source
      window and creates/updates one target_resolution record per combo.
      """
      from camp.apps.summaries.aggregators import rollup_summaries
      from camp.apps.summaries.models import MonitorSummary

      combos = (
          MonitorSummary.objects
          .filter(
              resolution=source_resolution,
              timestamp__gte=window_start,
              timestamp__lt=window_end,
          )
          .values_list('monitor_id', 'entry_type', 'stage', 'processor')
          .distinct()
      )

      for monitor_id, entry_type, stage, processor in combos:
          source_qs = MonitorSummary.objects.filter(
              monitor_id=monitor_id,
              entry_type=entry_type,
              stage=stage,
              processor=processor,
              resolution=source_resolution,
              timestamp__gte=window_start,
              timestamp__lt=window_end,
          )
          stats = rollup_summaries(source_qs)
          if stats is None:
              continue

          MonitorSummary.objects.update_or_create(
              monitor_id=monitor_id,
              timestamp=window_start,
              resolution=target_resolution,
              entry_type=entry_type,
              stage=stage,
              processor=processor,
              defaults=stats,
          )


  def rollup_region_summaries(target_resolution, source_resolution, window_start, window_end):
      """Same as rollup_monitor_summaries but for RegionSummary."""
      from camp.apps.summaries.aggregators import rollup_summaries
      from camp.apps.summaries.models import RegionSummary

      combos = (
          RegionSummary.objects
          .filter(
              resolution=source_resolution,
              timestamp__gte=window_start,
              timestamp__lt=window_end,
          )
          .values_list('region_id', 'entry_type', 'stage', 'processor')
          .distinct()
      )

      for region_id, entry_type, stage, processor in combos:
          source_qs = RegionSummary.objects.filter(
              region_id=region_id,
              entry_type=entry_type,
              stage=stage,
              processor=processor,
              resolution=source_resolution,
              timestamp__gte=window_start,
              timestamp__lt=window_end,
          )
          stats = rollup_summaries(source_qs)
          if stats is None:
              continue

          # station_count: max across the period (most monitors that ever contributed)
          station_count = source_qs.aggregate(
              max_stations=Max('station_count')
          )['max_stations'] or 0

          RegionSummary.objects.update_or_create(
              region_id=region_id,
              timestamp=window_start,
              resolution=target_resolution,
              entry_type=entry_type,
              stage=stage,
              processor=processor,
              defaults={**stats, 'station_count': station_count},
          )


  # ---- Periodic tasks ----

  def _yesterday():
      today = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
      return today - timedelta(days=1)


  def _last_month_start():
      import calendar
      today = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
      last_month = today - timedelta(days=1)
      return last_month.replace(day=1)


  def _last_quarter_start():
      today = timezone.now()
      quarter_month = ((today.month - 1) // 3) * 3 + 1
      current_quarter_start = today.replace(month=quarter_month, day=1, hour=0, minute=0, second=0, microsecond=0)
      if quarter_month == 1:
          return current_quarter_start.replace(year=current_quarter_start.year - 1, month=10)
      return current_quarter_start.replace(month=quarter_month - 3)


  def _last_season_start():
      today = timezone.now()
      end_month = today.month
      start_month = end_month - 3 if end_month > 3 else end_month + 9
      start_year = today.year if end_month > 3 else today.year - 1
      return today.replace(year=start_year, month=start_month, day=1, hour=0, minute=0, second=0, microsecond=0)


  @db_periodic_task(crontab(hour='0', minute='15'), priority=50)
  def daily_monitor_summaries(day=None):
      """Roll up yesterday's hourly MonitorSummary records into daily ones."""
      from camp.apps.summaries.models import BaseSummary
      day = day or _yesterday()
      rollup_monitor_summaries(BaseSummary.Resolution.DAILY, BaseSummary.Resolution.HOURLY, day, day + timedelta(days=1))


  @db_periodic_task(crontab(hour='0', minute='25'), priority=50)
  def daily_region_summaries(day=None):
      """Roll up yesterday's hourly RegionSummary records into daily ones."""
      from camp.apps.summaries.models import BaseSummary
      day = day or _yesterday()
      rollup_region_summaries(BaseSummary.Resolution.DAILY, BaseSummary.Resolution.HOURLY, day, day + timedelta(days=1))


  @db_periodic_task(crontab(day='1', hour='0', minute='30'), priority=50)
  def monthly_monitor_summaries(month_start=None):
      """Roll up last month's daily MonitorSummary records into monthly ones."""
      import calendar
      from camp.apps.summaries.models import BaseSummary
      month_start = month_start or _last_month_start()
      _, days_in_month = calendar.monthrange(month_start.year, month_start.month)
      rollup_monitor_summaries(BaseSummary.Resolution.MONTHLY, BaseSummary.Resolution.DAILY, month_start, month_start + timedelta(days=days_in_month))


  @db_periodic_task(crontab(day='1', hour='0', minute='40'), priority=50)
  def monthly_region_summaries(month_start=None):
      """Roll up last month's daily RegionSummary records into monthly ones."""
      import calendar
      from camp.apps.summaries.models import BaseSummary
      month_start = month_start or _last_month_start()
      _, days_in_month = calendar.monthrange(month_start.year, month_start.month)
      rollup_region_summaries(BaseSummary.Resolution.MONTHLY, BaseSummary.Resolution.DAILY, month_start, month_start + timedelta(days=days_in_month))


  @db_periodic_task(crontab(month='1,4,7,10', day='1', hour='0', minute='45'), priority=50)
  def quarterly_monitor_summaries(quarter_start=None):
      """Roll up last quarter's monthly MonitorSummary records into quarterly ones."""
      from camp.apps.summaries.models import BaseSummary
      quarter_start = quarter_start or _last_quarter_start()
      rollup_monitor_summaries(BaseSummary.Resolution.QUARTERLY, BaseSummary.Resolution.MONTHLY, quarter_start, quarter_start + timedelta(days=92))


  @db_periodic_task(crontab(month='1,4,7,10', day='1', hour='0', minute='50'), priority=50)
  def quarterly_region_summaries(quarter_start=None):
      """Roll up last quarter's monthly RegionSummary records into quarterly ones."""
      from camp.apps.summaries.models import BaseSummary
      quarter_start = quarter_start or _last_quarter_start()
      rollup_region_summaries(BaseSummary.Resolution.QUARTERLY, BaseSummary.Resolution.MONTHLY, quarter_start, quarter_start + timedelta(days=92))


  @db_periodic_task(crontab(month='3,6,9,12', day='1', hour='1', minute='0'), priority=50)
  def seasonal_monitor_summaries(season_start=None):
      """
      Roll up the past 3 months of monthly MonitorSummary records into a seasonal one.
      Runs Mar 1, Jun 1, Sep 1, Dec 1 to summarize the just-completed season.
      """
      from camp.apps.summaries.models import BaseSummary
      season_start = season_start or _last_season_start()
      rollup_monitor_summaries(BaseSummary.Resolution.SEASONAL, BaseSummary.Resolution.MONTHLY, season_start, season_start + timedelta(days=92))


  @db_periodic_task(crontab(month='3,6,9,12', day='1', hour='1', minute='10'), priority=50)
  def seasonal_region_summaries(season_start=None):
      """Roll up the past 3 months of monthly RegionSummary records into a seasonal one."""
      from camp.apps.summaries.models import BaseSummary
      season_start = season_start or _last_season_start()
      rollup_region_summaries(BaseSummary.Resolution.SEASONAL, BaseSummary.Resolution.MONTHLY, season_start, season_start + timedelta(days=92))


  @db_periodic_task(crontab(month='1', day='1', hour='1', minute='15'), priority=50)
  def yearly_monitor_summaries(year_start=None):
      """Roll up last year's monthly MonitorSummary records into yearly ones."""
      from camp.apps.summaries.models import BaseSummary
      if year_start is None:
          today = timezone.now()
          year_start = today.replace(year=today.year - 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
      rollup_monitor_summaries(BaseSummary.Resolution.YEARLY, BaseSummary.Resolution.MONTHLY, year_start, year_start.replace(year=year_start.year + 1))


  @db_periodic_task(crontab(month='1', day='1', hour='1', minute='20'), priority=50)
  def yearly_region_summaries(year_start=None):
      """Roll up last year's monthly RegionSummary records into yearly ones."""
      from camp.apps.summaries.models import BaseSummary
      if year_start is None:
          today = timezone.now()
          year_start = today.replace(year=today.year - 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
      rollup_region_summaries(BaseSummary.Resolution.YEARLY, BaseSummary.Resolution.MONTHLY, year_start, year_start.replace(year=year_start.year + 1))
  ```

- [ ] **Step 4: Run the tests**

  Run: `docker compose run --rm test pytest camp/apps/summaries/tests.py::RollupMonitorSummariesTests camp/apps/summaries/tests.py::RollupRegionSummariesTests -v`
  Expected: 3 passed

- [ ] **Step 5: Run the full suite**

  Run: `docker compose run --rm test pytest camp/apps/summaries/tests.py -v`
  Expected: all pass

- [ ] **Step 6: Commit**

  ```bash
  git add camp/apps/summaries/tasks.py camp/apps/summaries/tests.py
  git commit -m "Add rollup tasks for daily, monthly, quarterly, seasonal, and yearly summaries"
  ```

---

## Chunk 4: Admin

### Task 9: Admin

**Files:**
- Modify: `camp/apps/summaries/admin.py`

No tests needed for admin — it's read-only display.

- [ ] **Step 1: Implement admin**

  Replace `camp/apps/summaries/admin.py`:

  ```python
  from django.contrib import admin
  from django.db.models import Field

  from camp.apps.summaries.models import MonitorSummary, RegionSummary


  def _readonly(model):
      return [f.name for f in model._meta.get_fields() if isinstance(f, Field)]


  @admin.register(MonitorSummary)
  class MonitorSummaryAdmin(admin.ModelAdmin):
      list_display = ['monitor', 'entry_type', 'stage', 'processor', 'resolution', 'timestamp', 'mean', 'count', 'is_complete']
      list_filter = ['resolution', 'entry_type', 'stage', 'is_complete']
      search_fields = ['monitor__name']
      ordering = ['-timestamp']
      readonly_fields = _readonly(MonitorSummary)


  @admin.register(RegionSummary)
  class RegionSummaryAdmin(admin.ModelAdmin):
      list_display = ['region', 'entry_type', 'stage', 'processor', 'resolution', 'timestamp', 'mean', 'station_count', 'is_complete']
      list_filter = ['resolution', 'entry_type', 'stage', 'is_complete']
      search_fields = ['region__name']
      ordering = ['-timestamp']
      readonly_fields = _readonly(RegionSummary)
  ```

- [ ] **Step 2: Verify admin loads**

  Run: `docker compose run --rm web python manage.py check`
  Expected: System check identified no issues.

- [ ] **Step 3: Commit**

  ```bash
  git add camp/apps/summaries/admin.py
  git commit -m "Add MonitorSummary and RegionSummary admin"
  ```

---

### Task 10: Final verification

- [ ] **Step 1: Run the complete test suite for the app**

  Run: `docker compose run --rm test pytest camp/apps/summaries/ -v`
  Expected: all pass

- [ ] **Step 2: Run the full project test suite to check for regressions**

  Run: `docker compose run --rm test pytest`
  Expected: all pass (or same failures as before this branch)

- [ ] **Step 3: Commit if any fixes were needed**

  If any fixes were made to pass the full suite, commit them before declaring done.
