from datetime import timedelta

import numpy as np
from tdigest import TDigest

from django.test import TestCase
from django.utils import timezone

from camp.apps.entries.models import PM25
from camp.apps.monitors.models import Monitor
from camp.apps.qaqc.models import HealthCheck
from camp.apps.regions.models import Region
from camp.apps.summaries.aggregators import (
    LCS_WEIGHT,
    compute_monitor_summary,
    compute_region_summary,
    get_monitor_weight,
    rollup_summaries,
    tdigest_to_dict,
)
from camp.apps.summaries.models import BaseSummary, MonitorSummary, RegionSummary
from camp.apps.summaries.tasks import (
    rollup_monitor_summaries,
    rollup_region_summaries,
    summarize_monitor_hour,
    summarize_region_hour,
)


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


class RollupSummariesTests(TestCase):
    fixtures = ['purple-air.yaml']

    def setUp(self):
        self.monitor = Monitor.objects.first()
        self.hour = timezone.now().replace(minute=0, second=0, microsecond=0) - timedelta(hours=2)

    def _make_monitor_summary(self, hour, mean, count=10, expected=30):
        arr = np.array([mean] * count)
        digest = TDigest()
        digest.batch_update(arr.tolist())
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


class GetMonitorWeightTests(TestCase):
    fixtures = ['purple-air.yaml', 'regions.yaml']

    def setUp(self):
        self.monitor = Monitor.objects.first()
        self.hour = timezone.now().replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)

    def test_lcs_monitor_without_health_check_gets_full_lcs_weight(self):
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
        digest.batch_update(arr.tolist())
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
        if not self.region.boundary:
            self.skipTest('requires region with boundary')
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
        region_no_boundary = Region.objects.filter(boundary__isnull=True).first()
        if region_no_boundary is None:
            self.skipTest('no region without boundary in fixtures')
        result = compute_region_summary(
            region_no_boundary, self.hour, 'pm25', 'raw', ''
        )
        self.assertIsNone(result)


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


class SummarizeRegionHourTests(TestCase):
    fixtures = ['purple-air.yaml', 'regions.yaml']

    def setUp(self):
        self.monitor = Monitor.objects.first()
        self.hour = timezone.now().replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
        self.region = Region.objects.filter(boundary__isnull=False).first()
        if self.region is None:
            self.skipTest('no region with boundary in fixtures')
        self.monitor.position = self.region.boundary.geometry.centroid
        self.monitor.save()

    def _make_monitor_summary(self, mean=20.0):
        arr = np.array([mean] * 10)
        digest = TDigest()
        digest.batch_update(arr.tolist())
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


class RollupMonitorSummariesTests(TestCase):
    fixtures = ['purple-air.yaml']

    def setUp(self):
        self.monitor = Monitor.objects.first()
        today = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        self.yesterday = today - timedelta(days=1)

    def _make_hourly_summary(self, hour, mean=20.0):
        arr = np.array([mean] * 10)
        digest = TDigest()
        digest.batch_update(arr.tolist())
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
        digest.batch_update(arr.tolist())
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
            self._make_hourly_region_summary(
                self.yesterday + timedelta(hours=h),
                mean=10.0 * (h + 1),
                station_count=h + 1,
            )

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
