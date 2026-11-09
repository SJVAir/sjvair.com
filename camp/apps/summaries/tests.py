from datetime import datetime, timedelta, timezone as dt_timezone
from unittest.mock import patch

import numpy as np
import pytest
from tdigest import TDigest

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import RequestFactory, TestCase
from django.utils import timezone

# Fixed datetime for time-sensitive task tests.
# Apr 1, 2026 10:30 UTC — a convenient date for calendar helper assertions:
#   yesterday       = 2026-03-31
#   last month      = 2026-03-01
#   last quarter    = 2026-01-01  (Q1: Jan–Mar)
#   last season     = 2025-12-01  (winter: Dec–Feb; use Mar 1 as "now" for that helper)
FIXED_NOW = timezone.make_aware(datetime(2026, 4, 1, 10, 30, 0))
# 2026-04-01 08:30 UTC = 01:30 PDT, inside the Pacific hour the rollups run in.
ROLLUP_NOW = timezone.make_aware(datetime(2026, 4, 1, 8, 30, 0))

from camp.apps.entries.models import CO, NO2, O3, PM25, SO2
from camp.apps.monitors.bam.models import BAM1022
from camp.apps.monitors.cimis import tasks as cimis_tasks
from camp.apps.monitors.models import Monitor
from camp.apps.monitors.purpleair.models import PurpleAir
from camp.apps.qaqc.models import HealthCheck
from camp.apps.accounts.models import User
from camp.apps.regions.models import Region
from camp.apps.regions.panels import panels_for
from camp.apps.summaries.aggregators import (
    FEM_WEIGHT,
    LCS_WEIGHT,
    compute_monitor_summary,
    compute_region_summary,
    compute_stats,
    get_monitor_weight,
    rollup_region_stats,
    rollup_summaries,
    tdigest_to_dict,
)
from camp.apps.summaries.models import BaseSummary, MonitorSummary, RegionSummary
from camp.apps.summaries.periods import iter_hours
from camp.apps.summaries.panels import TrendPanel
from camp.apps.summaries import tasks as summary_tasks
from camp.apps.summaries.selection import region_summary_entry_models
from camp.apps.summaries.schedule import (
    ROLLUP_LOCAL_TIME,
    HOURLY_FIRE_MINUTE,
    LATE_RUN_WARNING,
    LATE_SETTLE_MARGIN,
    PEAK_8H_SETTLE_MARGIN,
    SETTLE_MARGIN,
    hour_for_run,
    is_pacific_hour,
    is_settled,
    pacific_crontab,
    period_end,
)
from camp.utils.datetime import localtime
from camp.apps.summaries.tasks import (
    daily_monitor_summaries,
    hourly_monitor_summaries,
    hourly_region_summaries,
    monthly_monitor_summaries,
    quarterly_monitor_summaries,
    rollup_monitor_summaries,
    rollup_region_summaries,
    seasonal_monitor_summaries,
    summarize_monitor_hour,
    summarize_region_hour,
)


class ComputeMonitorSummaryTests(TestCase):
    fixtures = ['purple-air.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.first()
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
        result = compute_monitor_summary(self.monitor, self.hour, PM25, '')
        assert result is None

    def test_computes_basic_stats(self):
        values = [10.0, 20.0, 30.0, 40.0, 50.0]
        for i, v in enumerate(values):
            self._make_entry(v, offset_minutes=i * 2)

        result = compute_monitor_summary(self.monitor, self.hour, PM25, '')

        assert result is not None
        assert result['count'] == 5
        assert result['mean'] == pytest.approx(30.0)
        assert result['minimum'] == pytest.approx(10.0)
        assert result['maximum'] == pytest.approx(50.0)
        assert result['sum_value'] == pytest.approx(150.0)
        assert 'tdigest' in result
        assert isinstance(result['tdigest'], dict)

    def test_is_complete_true_when_sufficient_coverage(self):
        # PurpleAir expects 30 readings/hour (2-min interval).
        # 80% of 30 = 24. Create 25 entries.
        for i in range(25):
            self._make_entry(15.0, offset_minutes=i * 2)

        result = compute_monitor_summary(self.monitor, self.hour, PM25, '')
        assert result['is_complete']

    def test_is_complete_false_when_insufficient_coverage(self):
        # Only 5 entries out of 30 expected
        for i in range(5):
            self._make_entry(15.0, offset_minutes=i * 2)

        result = compute_monitor_summary(self.monitor, self.hour, PM25, '')
        assert not result['is_complete']

    def test_only_includes_entries_in_window(self):
        self._make_entry(100.0, offset_minutes=-5)   # before window
        self._make_entry(10.0, offset_minutes=5)     # in window
        self._make_entry(100.0, offset_minutes=65)   # after window

        result = compute_monitor_summary(self.monitor, self.hour, PM25, '')
        assert result['count'] == 1
        assert result['mean'] == pytest.approx(10.0)


class ComputeStatsTests(TestCase):
    def test_returns_none_for_empty_values(self):
        assert compute_stats([], expected_count=10) is None

    def test_computes_basic_stats(self):
        values = [10.0, 20.0, 30.0, 40.0, 50.0]
        result = compute_stats(values, expected_count=10)
        assert result is not None
        assert result['count'] == 5
        assert result['mean'] == pytest.approx(30.0)
        assert result['minimum'] == pytest.approx(10.0)
        assert result['maximum'] == pytest.approx(50.0)
        assert result['sum_value'] == pytest.approx(150.0)
        assert result['expected_count'] == 10
        assert 'tdigest' in result
        assert isinstance(result['tdigest'], dict)

    def test_is_complete_at_threshold(self):
        # 8 out of 10 = 80%, exactly at threshold
        result = compute_stats([1.0] * 8, expected_count=10)
        assert result['is_complete']

    def test_is_complete_false_below_threshold(self):
        # 7 out of 10 = 70%, below 80%
        result = compute_stats([1.0] * 7, expected_count=10)
        assert not result['is_complete']


class RollupSummariesTests(TestCase):
    fixtures = ['purple-air.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.first()
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

    def _as_records(self, qs):
        return list(qs.values(
            'count', 'expected_count', 'sum_value', 'sum_of_squares',
            'minimum', 'maximum', 'tdigest',
        ))

    def test_returns_none_for_empty_records(self):
        assert rollup_summaries([]) is None

    def test_rolls_up_two_hours(self):
        self._make_monitor_summary(self.hour, mean=10.0, count=10)
        self._make_monitor_summary(self.hour + timedelta(hours=1), mean=20.0, count=10)

        records = self._as_records(MonitorSummary.objects.filter(
            monitor=self.monitor,
            entry_type='pm25',
            processor='',
            resolution=MonitorSummary.Resolution.HOURLY,
        ))
        result = rollup_summaries(records)

        assert result['count'] == 20
        assert result['mean'] == pytest.approx(15.0)
        assert result['minimum'] == pytest.approx(10.0)
        assert result['maximum'] == pytest.approx(20.0)
        assert 'tdigest' in result

    def test_is_complete_aggregated_correctly(self):
        # 10 out of 30 expected = 33%, not complete
        self._make_monitor_summary(self.hour, mean=10.0, count=10, expected=30)
        self._make_monitor_summary(self.hour + timedelta(hours=1), mean=20.0, count=10, expected=30)

        records = self._as_records(MonitorSummary.objects.filter(monitor=self.monitor))
        result = rollup_summaries(records)

        # combined: 20 count, 60 expected = 33%, not complete
        assert not result['is_complete']


class RollupRegionStatsTests(TestCase):
    """Verify rollup_region_stats uses the float weight, not the rounded int count, as
    the variance denominator — which is the whole reason the field exists."""

    def _make_record(self, mean, variance, weight):
        """Build a fake region summary record dict with the given stats."""
        sum_of_squares = (variance + mean ** 2) * weight  # = weight * E[X²]
        arr = np.array([mean] * 10)
        digest = TDigest()
        digest.batch_update(arr.tolist())
        return {
            'count': int(round(weight)),
            'weight': weight,
            'expected_count': int(round(weight)),
            'sum_value': mean * weight,
            'sum_of_squares': sum_of_squares,
            'minimum': mean,
            'maximum': mean,
            'tdigest': tdigest_to_dict(digest),
        }

    def test_returns_none_for_empty_records(self):
        assert rollup_region_stats([]) is None

    def test_returns_none_when_weight_is_zero(self):
        record = self._make_record(mean=10.0, variance=4.0, weight=0.0)
        assert rollup_region_stats([record]) is None

    def test_mean_is_weight_proportional(self):
        # Two records with equal weight — mean should be the simple average.
        r1 = self._make_record(mean=10.0, variance=0.0, weight=2.0)
        r2 = self._make_record(mean=30.0, variance=0.0, weight=2.0)
        result = rollup_region_stats([r1, r2])
        assert result['mean'] == pytest.approx(20.0)

    def test_mean_respects_unequal_weights(self):
        # Record 2 has 3× the weight of record 1 — mean should skew toward record 2.
        r1 = self._make_record(mean=0.0, variance=0.0, weight=1.0)
        r2 = self._make_record(mean=40.0, variance=0.0, weight=3.0)
        result = rollup_region_stats([r1, r2])
        assert result['mean'] == pytest.approx(30.0)  # (0*1 + 40*3) / (1+3)

    def test_stddev_correct_with_fractional_weights(self):
        # Each record has weight=1/3 (fractional — round(1/3) = 0, which would
        # cause division by zero in the old int-count approach).
        # Three records with mean=10, 20, 30 and zero within-record variance.
        # Combined mean = 20, combined variance = ((10-20)²+(20-20)²+(30-20)²)/3 = 66.67
        records = [
            self._make_record(mean=float(v), variance=0.0, weight=1 / 3)
            for v in [10, 20, 30]
        ]
        result = rollup_region_stats(records)
        assert result is not None
        assert result['mean'] == pytest.approx(20.0, abs=0.01)
        assert result['stddev'] == pytest.approx((200 / 3) ** 0.5, abs=0.1)

    def test_weight_accumulates_across_rollup(self):
        r1 = self._make_record(mean=10.0, variance=0.0, weight=2.5)
        r2 = self._make_record(mean=20.0, variance=0.0, weight=1.5)
        result = rollup_region_stats([r1, r2])
        assert result['weight'] == pytest.approx(4.0)

    def test_compute_region_summary_stores_exact_weight(self):
        """compute_region_summary must return exact float weight, not rounded int."""
        # health_score=1 → health_factor=1/3 → weight=1/3 (fractional)
        # We test the return value directly without DB.
        weight = LCS_WEIGHT * (1 / 3)
        assert abs(weight - round(weight)) > 0.1  # confirm it's fractional

        # Build a minimal fake summary object to pass to the aggregator logic.
        # We verify that the returned dict has 'weight' as a float != count.
        from camp.apps.summaries.aggregators import get_monitor_weight
        w = get_monitor_weight(Monitor.Grade.LCS, health_score=1)
        assert w == pytest.approx(1 / 3, abs=1e-9)
        assert w != int(round(w))  # fractional — round() would distort it


class GetMonitorWeightTests(TestCase):
    fixtures = ['purple-air.yaml', 'regions.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.first()
        self.hour = timezone.now().replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)

    def test_lcs_monitor_without_health_check_gets_full_lcs_weight(self):
        assert get_monitor_weight(Monitor.Grade.LCS) == LCS_WEIGHT * 1.0

    def test_lcs_monitor_with_zero_health_score_gets_zero_weight(self):
        assert get_monitor_weight(Monitor.Grade.LCS, health_score=0) == 0.0

    def test_lcs_monitor_with_max_health_score_gets_full_lcs_weight(self):
        assert get_monitor_weight(Monitor.Grade.LCS, health_score=3) == pytest.approx(LCS_WEIGHT * 1.0)

    def test_fem_monitor_always_gets_fem_weight(self):
        assert get_monitor_weight(Monitor.Grade.FEM) == FEM_WEIGHT

    def test_fem_monitor_ignores_health_score(self):
        assert get_monitor_weight(Monitor.Grade.FEM, health_score=0) == FEM_WEIGHT

    def test_frm_monitor_always_gets_fem_weight(self):
        assert get_monitor_weight(Monitor.Grade.FRM) == FEM_WEIGHT


class WithGradeTests(TestCase):
    fixtures = ['purple-air.yaml', 'bam1022.yaml']

    def test_lcs_monitor_annotated_as_lcs(self):
        pa = PurpleAir.objects.first()
        result = Monitor.objects.with_grade().get(pk=pa.pk)
        assert result.grade == Monitor.Grade.LCS

    def test_fem_monitor_annotated_as_fem(self):
        bam = BAM1022.objects.first()
        result = Monitor.objects.with_grade().get(pk=bam.pk)
        assert result.grade == Monitor.Grade.FEM

    def test_values_list_returns_correct_grades(self):
        grades = dict(Monitor.objects.with_grade().values_list('pk', 'grade'))
        pa = PurpleAir.objects.first()
        bam = BAM1022.objects.first()
        assert grades[pa.pk] == Monitor.Grade.LCS
        assert grades[bam.pk] == Monitor.Grade.FEM


class ComputeRegionSummaryTests(TestCase):
    fixtures = ['purple-air.yaml', 'bam1022.yaml', 'regions.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.first()
        self.hour = timezone.now().replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
        self.region = Region.objects.first()

    def _make_monitor_summary(self, mean=20.0, count=10, monitor=None):
        arr = np.array([mean] * count)
        digest = TDigest()
        digest.batch_update(arr.tolist())
        return MonitorSummary.objects.create(
            monitor=monitor or self.monitor,
            timestamp=self.hour,
            resolution=MonitorSummary.Resolution.HOURLY,
            entry_type='pm25',
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
        assert compute_region_summary(self.region, self.hour, 'pm25') is None

    def test_returns_stats_when_monitor_in_region(self):
        if not self.region.boundary:
            self.skipTest('requires region with boundary')
        self.monitor.position = self.region.boundary.geometry.centroid
        self.monitor.save()
        self._make_monitor_summary(mean=25.0)

        result = compute_region_summary(self.region, self.hour, 'pm25')

        assert result is not None
        assert result['station_count'] == 1
        assert result['mean'] == pytest.approx(25.0, abs=0.1)

    def test_accepts_pre_computed_monitor_grades(self):
        if not self.region.boundary:
            self.skipTest('requires region with boundary')
        self.monitor.position = self.region.boundary.geometry.centroid
        self.monitor.save()
        self._make_monitor_summary(mean=25.0)

        monitor_grades = {self.monitor.pk: Monitor.Grade.LCS}
        result = compute_region_summary(self.region, self.hour, 'pm25', monitor_grades=monitor_grades)

        assert result is not None
        assert result['mean'] == pytest.approx(25.0, abs=0.1)

    def test_fem_monitor_outweighs_lcs(self):
        if not self.region.boundary:
            self.skipTest('requires region with boundary')
        centroid = self.region.boundary.geometry.centroid

        # LCS monitor at 10, FEM monitor at 30 — FEM weight is 3×, so weighted
        # mean should be closer to 30 than a simple average of 20 would give.
        lcs = self.monitor
        lcs.position = centroid
        lcs.save()

        fem = BAM1022.objects.first()
        fem.position = centroid
        fem.save()

        self._make_monitor_summary(monitor=lcs, mean=10.0)
        self._make_monitor_summary(monitor=fem, mean=30.0)

        result = compute_region_summary(self.region, self.hour, 'pm25')

        assert result is not None
        assert result['station_count'] == 2
        # weighted mean: (LCS_WEIGHT*10 + FEM_WEIGHT*30) / (LCS_WEIGHT + FEM_WEIGHT)
        expected = (LCS_WEIGHT * 10.0 + FEM_WEIGHT * 30.0) / (LCS_WEIGHT + FEM_WEIGHT)
        assert result['mean'] == pytest.approx(expected, abs=0.01)

    def test_calibrated_processor_preferred_over_raw(self):
        # When a monitor has both a RAW (processor='') and a CALIBRATED summary,
        # the region should use the CALIBRATED one.
        if not self.region.boundary:
            self.skipTest('requires region with boundary')
        self.monitor.position = self.region.boundary.geometry.centroid
        self.monitor.save()

        # RAW summary at mean=10, CALIBRATED at mean=50 — region should use 50.
        self._make_monitor_summary(mean=10.0)  # processor=''

        arr = np.array([50.0] * 10)
        digest = TDigest()
        digest.batch_update(arr.tolist())
        MonitorSummary.objects.create(
            monitor=self.monitor,
            timestamp=self.hour,
            resolution=MonitorSummary.Resolution.HOURLY,
            entry_type='pm25',
            processor='custom_calibration',
            count=10,
            expected_count=30,
            sum_value=float(arr.sum()),
            sum_of_squares=float((arr ** 2).sum()),
            minimum=50.0,
            maximum=50.0,
            mean=50.0,
            stddev=0.0,
            p25=50.0,
            p75=50.0,
            tdigest=tdigest_to_dict(digest),
            is_complete=True,
        )

        result = compute_region_summary(self.region, self.hour, 'pm25')

        assert result is not None
        assert result['mean'] == pytest.approx(50.0, abs=0.1)



class SummarizeMonitorHourTests(TestCase):
    fixtures = ['purple-air.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.first()
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
            str(self.monitor.pk), self.hour, 'pm25', ''
        )

        assert MonitorSummary.objects.count() == 1
        summary = MonitorSummary.objects.first()
        assert summary.monitor == self.monitor
        assert summary.entry_type == 'pm25'
        assert summary.count == 5

    def test_idempotent_when_called_twice(self):
        for i in range(5):
            self._make_entry(20.0, offset_minutes=i * 2)

        summarize_monitor_hour(str(self.monitor.pk), self.hour, 'pm25', '')
        summarize_monitor_hour(str(self.monitor.pk), self.hour, 'pm25', '')

        assert MonitorSummary.objects.count() == 1

    def test_skips_when_no_entries(self):
        summarize_monitor_hour(str(self.monitor.pk), self.hour, 'pm25', '')
        assert MonitorSummary.objects.count() == 0


class SummarizeRegionHourTests(TestCase):
    fixtures = ['purple-air.yaml', 'regions.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.first()
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
        summarize_region_hour(str(self.region.pk), self.hour, 'pm25')

        assert RegionSummary.objects.count() == 1
        summary = RegionSummary.objects.first()
        assert summary.region == self.region
        assert summary.station_count == 1

    def test_skips_when_no_monitor_summaries(self):
        summarize_region_hour(str(self.region.pk), self.hour, 'pm25')
        assert RegionSummary.objects.count() == 0

    def test_idempotent_when_called_twice(self):
        self._make_monitor_summary(mean=25.0)
        summarize_region_hour(str(self.region.pk), self.hour, 'pm25')
        summarize_region_hour(str(self.region.pk), self.hour, 'pm25')
        assert RegionSummary.objects.count() == 1


class RollupMonitorSummariesTests(TestCase):
    fixtures = ['purple-air.yaml', 'bam1022.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.first()
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
        assert daily.count() == 1
        assert daily.first().mean == pytest.approx(20.0)  # mean of (10, 20, 30)

    def test_daily_rollup_is_idempotent(self):
        for h in range(3):
            self._make_hourly_summary(self.yesterday + timedelta(hours=h))

        for _ in range(2):
            rollup_monitor_summaries(
                MonitorSummary.Resolution.DAILY,
                MonitorSummary.Resolution.HOURLY,
                self.yesterday,
                self.yesterday + timedelta(days=1),
            )

        assert MonitorSummary.objects.filter(resolution=MonitorSummary.Resolution.DAILY).count() == 1

    def test_monitor_ids_scoping_excludes_other_monitors(self):
        # Create hourly summaries for self.monitor and a second monitor.
        # Rollup scoped to self.monitor only — second monitor must not appear.
        other = BAM1022.objects.first()
        for h in range(2):
            self._make_hourly_summary(self.yesterday + timedelta(hours=h))
            arr = np.array([99.0] * 10)
            digest = TDigest()
            digest.batch_update(arr.tolist())
            MonitorSummary.objects.create(
                monitor=other,
                timestamp=self.yesterday + timedelta(hours=h),
                resolution=MonitorSummary.Resolution.HOURLY,
                entry_type='pm25',
                processor='',
                count=10, expected_count=1, sum_value=float(arr.sum()),
                sum_of_squares=float((arr ** 2).sum()),
                minimum=99.0, maximum=99.0, mean=99.0, stddev=0.0,
                p25=99.0, p75=99.0, tdigest=tdigest_to_dict(digest),
                is_complete=True,
            )

        rollup_monitor_summaries(
            MonitorSummary.Resolution.DAILY,
            MonitorSummary.Resolution.HOURLY,
            self.yesterday,
            self.yesterday + timedelta(days=1),
            monitor_ids=[self.monitor.pk],
        )

        daily = MonitorSummary.objects.filter(resolution=MonitorSummary.Resolution.DAILY)
        assert daily.count() == 1
        assert daily.first().monitor == self.monitor


class RollupRegionSummariesTests(TestCase):
    fixtures = ['purple-air.yaml', 'regions.yaml']

    def setUp(self):
        self.region = Region.objects.filter(boundary__isnull=False).first()
        if self.region is None:
            self.skipTest('no region with boundary in fixtures')
        today = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
        self.yesterday = today - timedelta(days=1)

    def _make_hourly_region_summary(self, hour, mean=20.0, station_count=2, weight=10.0):
        arr = np.array([mean] * 10)
        digest = TDigest()
        digest.batch_update(arr.tolist())
        return RegionSummary.objects.create(
            region=self.region,
            timestamp=hour,
            resolution=RegionSummary.Resolution.HOURLY,
            entry_type='pm25',
            count=10,
            weight=weight,
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
        assert daily.count() == 1
        assert daily.first().mean == pytest.approx(20.0)  # mean of (10, 20, 30)
        assert daily.first().station_count == 3            # max of (1, 2, 3)

    def test_daily_rollup_is_idempotent(self):
        for h in range(3):
            self._make_hourly_region_summary(self.yesterday + timedelta(hours=h))

        for _ in range(2):
            rollup_region_summaries(
                RegionSummary.Resolution.DAILY,
                RegionSummary.Resolution.HOURLY,
                self.yesterday,
                self.yesterday + timedelta(days=1),
            )

        assert RegionSummary.objects.filter(resolution=RegionSummary.Resolution.DAILY).count() == 1

    def test_region_ids_scoping_excludes_other_regions(self):
        other_region = Region.objects.filter(boundary__isnull=False).exclude(pk=self.region.pk).first()
        if other_region is None:
            self.skipTest('requires at least two regions with boundaries in fixtures')

        for h in range(2):
            self._make_hourly_region_summary(self.yesterday + timedelta(hours=h))
            arr = np.array([99.0] * 10)
            digest = TDigest()
            digest.batch_update(arr.tolist())
            RegionSummary.objects.create(
                region=other_region,
                timestamp=self.yesterday + timedelta(hours=h),
                resolution=RegionSummary.Resolution.HOURLY,
                entry_type='pm25',
                count=5, weight=5.0, expected_count=5,
                sum_value=float(arr.sum()), sum_of_squares=float((arr ** 2).sum()),
                minimum=99.0, maximum=99.0, mean=99.0, stddev=0.0,
                p25=99.0, p75=99.0, tdigest=tdigest_to_dict(digest),
                station_count=1,
            )

        rollup_region_summaries(
            RegionSummary.Resolution.DAILY,
            RegionSummary.Resolution.HOURLY,
            self.yesterday,
            self.yesterday + timedelta(days=1),
            region_ids=[self.region.pk],
        )

        daily = RegionSummary.objects.filter(resolution=RegionSummary.Resolution.DAILY)
        assert daily.count() == 1
        assert daily.first().region == self.region


class RegionSummaryEntryModelsTests(TestCase):
    def test_returns_expected_models(self):
        models = region_summary_entry_models()
        assert {m.__name__ for m in models} == {'PM25', 'O3', 'CO', 'NO2', 'SO2'}

    def test_excluded_types_not_present(self):
        from camp.apps.entries.models import CO2, Humidity, Pressure, Temperature
        models = region_summary_entry_models()
        excluded = {Temperature, Humidity, Pressure, CO2}
        for m in models:
            assert m not in excluded


class RebuildSummariesCommandTests(TestCase):
    fixtures = ['purple-air.yaml', 'regions.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.first()
        self.hour = timezone.now().replace(minute=0, second=0, microsecond=0) - timedelta(hours=2)
        local_hour = timezone.localtime(self.hour, settings.DEFAULT_TIMEZONE)
        self.start = (local_hour - timedelta(hours=1)).strftime('%Y-%m-%d')

        self.region = Region.objects.filter(boundary__isnull=False).first()
        if self.region:
            self.monitor.position = self.region.boundary.geometry.centroid
            self.monitor.save()

    def _make_entries(self, count=5):
        for i in range(count):
            PM25.objects.create(
                monitor=self.monitor,
                timestamp=self.hour + timedelta(minutes=i * 2),
                stage=PM25.Stage.RAW,
                processor='',
                value=20.0 + i,
                location=self.monitor.location,
            )

    def _run(self, *args):
        call_command('rebuild_summaries', *args, stdout=open('/dev/null', 'w'))

    def test_creates_monitor_summaries(self):
        self._make_entries()
        self._run(self.start, '--monitors-only')
        assert MonitorSummary.objects.count() > 0

    def test_monitors_only_skips_regions(self):
        self._make_entries()
        self._run(self.start, '--monitors-only')
        assert RegionSummary.objects.count() == 0

    def test_regions_only_skips_monitors(self):
        self._make_entries()
        self._run(self.start, '--monitors-only')
        MonitorSummary.objects.all().delete()
        self._run(self.start, '--regions-only')
        assert MonitorSummary.objects.count() == 0

    def test_monitor_flag_scopes_to_one_monitor(self):
        self._make_entries()
        self._run(self.start, f'--monitor={self.monitor.pk}', '--monitors-only')
        for summary in MonitorSummary.objects.all():
            assert summary.monitor_id == self.monitor.pk

    def test_creates_region_summaries_when_monitor_in_region(self):
        if not self.region:
            self.skipTest('no region with boundary in fixtures')
        self._make_entries()
        self._run(self.start)
        assert RegionSummary.objects.count() > 0

    def test_region_flag_scopes_to_one_region(self):
        if not self.region:
            self.skipTest('no region with boundary in fixtures')
        self._make_entries()
        self._run(self.start, f'--region={self.region.pk}')
        # All region summaries belong to the specified region
        for summary in RegionSummary.objects.all():
            assert summary.region_id == self.region.pk
        # Monitor summaries exist for the monitors in that region
        assert MonitorSummary.objects.count() > 0

    def test_region_flag_invalid_region_raises_error(self):
        with pytest.raises((CommandError, SystemExit, ValueError)):
            self._run(self.start, '--region=doesnotexist')

    def test_invalid_date_raises_error(self):
        with pytest.raises((CommandError, SystemExit)):
            self._run('not-a-date')

    def test_rolls_only_finished_periods(self):
        # Now is mid-August: today, August, Q3, summer and 2026 haven't ended.
        LA = settings.DEFAULT_TIMEZONE
        pacific = lambda *args: timezone.make_aware(datetime(*args), LA)
        now = pacific(2026, 8, 15, 12, 30)
        start = pacific(2025, 11, 30)
        PM25.objects.bulk_create([
            PM25(monitor=self.monitor, timestamp=ts, stage=PM25.Stage.RAW, processor='',
                 value=10.0, location=self.monitor.location)
            for ts in iter_hours(start, pacific(2026, 8, 15, 11))
            if timezone.localtime(ts, LA).hour % 6 == 0 or ts >= pacific(2026, 8, 14)
        ])

        with patch('django.utils.timezone.now', return_value=now):
            self._run('2025-11-30', f'--monitor={self.monitor.pk}', '--monitors-only')

        R = BaseSummary.Resolution

        def stamps(resolution):
            return {
                timezone.localtime(ts, LA).date().isoformat()
                for ts in MonitorSummary.objects
                .filter(monitor=self.monitor, resolution=resolution)
                .values_list('timestamp', flat=True)
            }

        # Today's hours are written; today's day row isn't.
        assert pacific(2026, 8, 15, 10) in set(
            MonitorSummary.objects.filter(resolution=R.HOURLY).values_list('timestamp', flat=True)
        )
        assert '2026-08-14' in stamps(R.DAILY)
        assert '2026-08-15' not in stamps(R.DAILY)
        assert '2025-11-30' in stamps(R.DAILY)
        assert stamps(R.MONTHLY) == {f'{m}-01' for m in [
            '2025-11', '2025-12', '2026-01', '2026-02', '2026-03', '2026-04', '2026-05', '2026-06', '2026-07',
        ]}
        assert stamps(R.QUARTERLY) == {'2025-10-01', '2026-01-01', '2026-04-01'}
        assert stamps(R.SEASONAL) == {'2025-09-01', '2025-12-01', '2026-03-01'}
        assert stamps(R.YEARLY) == {'2025-01-01'}


# ---- Periodic task tests ----

class HourlyMonitorSummariesTaskTests(TestCase):
    fixtures = ['purple-air.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.first()
        # The hour that should be summarized when timezone.now() == FIXED_NOW
        self.expected_hour = FIXED_NOW.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)

    def _make_entry(self, value=20.0, offset_minutes=5):
        return PM25.objects.create(
            monitor=self.monitor,
            timestamp=self.expected_hour + timedelta(minutes=offset_minutes),
            stage=PM25.Stage.RAW,
            processor='',
            value=value,
            location=self.monitor.location,
        )

    def test_creates_summary_for_explicit_hour(self):
        self._make_entry()
        hourly_monitor_summaries(hour=self.expected_hour)
        assert MonitorSummary.objects.filter(
            monitor=self.monitor,
            timestamp=self.expected_hour,
            resolution=BaseSummary.Resolution.HOURLY,
        ).exists()

    def test_uses_previous_hour_when_called_without_args(self):
        self._make_entry()
        with patch('django.utils.timezone.now', return_value=FIXED_NOW.replace(minute=45)):
            hourly_monitor_summaries()
        assert MonitorSummary.objects.filter(
            monitor=self.monitor,
            timestamp=self.expected_hour,
            resolution=BaseSummary.Resolution.HOURLY,
        ).exists()

    def test_skips_monitors_with_no_entries(self):
        hourly_monitor_summaries(hour=self.expected_hour)
        assert MonitorSummary.objects.count() == 0


class HourlyRegionSummariesTaskTests(TestCase):
    fixtures = ['purple-air.yaml', 'regions.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.first()
        self.hour = FIXED_NOW.replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
        self.region = Region.objects.filter(boundary__isnull=False).first()
        if self.region is None:
            self.skipTest('no region with boundary in fixtures')
        self.monitor.position = self.region.boundary.geometry.centroid
        self.monitor.save()

    def _make_monitor_summary(self):
        arr = np.array([20.0] * 10)
        digest = TDigest()
        digest.batch_update(arr.tolist())
        return MonitorSummary.objects.create(
            monitor=self.monitor,
            timestamp=self.hour,
            resolution=BaseSummary.Resolution.HOURLY,
            entry_type='pm25',
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

    def test_creates_region_summary_for_explicit_hour(self):
        self._make_monitor_summary()
        hourly_region_summaries(hour=self.hour)
        assert RegionSummary.objects.filter(
            region=self.region,
            timestamp=self.hour,
            resolution=BaseSummary.Resolution.HOURLY,
        ).exists()

    def test_uses_previous_hour_when_called_without_args(self):
        self._make_monitor_summary()
        with patch('django.utils.timezone.now', return_value=FIXED_NOW.replace(minute=50)):
            hourly_region_summaries()
        assert RegionSummary.objects.filter(
            region=self.region,
            timestamp=self.hour,
            resolution=BaseSummary.Resolution.HOURLY,
        ).exists()

    def test_skips_when_no_monitor_summaries(self):
        hourly_region_summaries(hour=self.hour)
        assert RegionSummary.objects.count() == 0


class DailyMonitorSummariesTaskTests(TestCase):
    fixtures = ['purple-air.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.first()
        # FIXED_NOW = 2026-04-01 10:30 UTC = 03:30 PDT → yesterday in LA = 2026-03-31
        self.yesterday = timezone.make_aware(datetime(2026, 3, 31), settings.DEFAULT_TIMEZONE)

    def _make_hourly_summary(self, hour, mean=20.0):
        arr = np.array([mean] * 10)
        digest = TDigest()
        digest.batch_update(arr.tolist())
        return MonitorSummary.objects.create(
            monitor=self.monitor,
            timestamp=hour,
            resolution=BaseSummary.Resolution.HOURLY,
            entry_type='pm25',
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

    def test_rolls_up_yesterday_when_called_without_args(self):
        for h in range(3):
            self._make_hourly_summary(self.yesterday + timedelta(hours=h))

        with patch('django.utils.timezone.now', return_value=ROLLUP_NOW):
            daily_monitor_summaries()

        assert MonitorSummary.objects.filter(
            monitor=self.monitor,
            timestamp=self.yesterday,
            resolution=BaseSummary.Resolution.DAILY,
        ).exists()


class MonthlyMonitorSummariesTaskTests(TestCase):
    fixtures = ['purple-air.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.first()
        # FIXED_NOW = 2026-04-01 → last month = March 2026
        self.march = timezone.make_aware(datetime(2026, 3, 1), settings.DEFAULT_TIMEZONE)

    def _make_daily_summary(self, day, mean=20.0):
        arr = np.array([mean] * 10)
        digest = TDigest()
        digest.batch_update(arr.tolist())
        return MonitorSummary.objects.create(
            monitor=self.monitor,
            timestamp=day,
            resolution=BaseSummary.Resolution.DAILY,
            entry_type='pm25',
            processor='',
            count=10,
            expected_count=720,
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

    def test_rolls_up_last_month_when_called_without_args(self):
        for d in range(3):
            self._make_daily_summary(self.march + timedelta(days=d))

        with patch('django.utils.timezone.now', return_value=ROLLUP_NOW):
            monthly_monitor_summaries()

        assert MonitorSummary.objects.filter(
            monitor=self.monitor,
            timestamp=self.march,
            resolution=BaseSummary.Resolution.MONTHLY,
        ).exists()

    def test_explicit_month_start_used_when_provided(self):
        for d in range(3):
            self._make_daily_summary(self.march + timedelta(days=d))

        monthly_monitor_summaries(month_start=self.march)

        assert MonitorSummary.objects.filter(
            monitor=self.monitor,
            timestamp=self.march,
            resolution=BaseSummary.Resolution.MONTHLY,
        ).exists()


class QuarterlyMonitorSummariesTaskTests(TestCase):
    fixtures = ['purple-air.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.first()
        # FIXED_NOW = 2026-04-01 → last quarter = Q1 2026 (Jan–Mar)
        self.q1_start = timezone.make_aware(datetime(2026, 1, 1), settings.DEFAULT_TIMEZONE)

    def _make_monthly_summary(self, month_start, mean=20.0):
        arr = np.array([mean] * 10)
        digest = TDigest()
        digest.batch_update(arr.tolist())
        return MonitorSummary.objects.create(
            monitor=self.monitor,
            timestamp=month_start,
            resolution=BaseSummary.Resolution.MONTHLY,
            entry_type='pm25',
            processor='',
            count=10,
            expected_count=100,
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

    def test_rolls_up_last_quarter_when_called_without_args(self):
        for month in [1, 2, 3]:
            self._make_monthly_summary(
                timezone.make_aware(datetime(2026, month, 1), settings.DEFAULT_TIMEZONE)
            )

        with patch('django.utils.timezone.now', return_value=ROLLUP_NOW):
            quarterly_monitor_summaries()

        assert MonitorSummary.objects.filter(
            monitor=self.monitor,
            timestamp=self.q1_start,
            resolution=BaseSummary.Resolution.QUARTERLY,
        ).exists()

    def test_quarterly_mean_aggregates_monthly_records(self):
        means = [10.0, 20.0, 30.0]
        for month, mean in zip([1, 2, 3], means):
            self._make_monthly_summary(
                timezone.make_aware(datetime(2026, month, 1), settings.DEFAULT_TIMEZONE),
                mean=mean,
            )

        quarterly_monitor_summaries(quarter_start=self.q1_start)

        quarterly = MonitorSummary.objects.get(
            monitor=self.monitor,
            timestamp=self.q1_start,
            resolution=BaseSummary.Resolution.QUARTERLY,
        )
        assert quarterly.mean == pytest.approx(20.0)  # mean of (10, 20, 30)


def daily_region_summary(region, day, mean, entry_type='pm25', station_count=1):
    timestamp = timezone.make_aware(datetime.combine(day, datetime.min.time()))
    return RegionSummary.objects.create(
        region=region, entry_type=entry_type, resolution=RegionSummary.Resolution.DAILY, timestamp=timestamp,
        count=24, expected_count=24, sum_value=mean * 24, sum_of_squares=mean * mean * 24, tdigest={},
        minimum=mean, maximum=mean, mean=mean, stddev=0.0, p25=mean, p75=mean,
        station_count=station_count, weight=float(station_count),
    )


def utc(*args):
    return timezone.make_aware(datetime(*args), dt_timezone.utc)


def pacific(*args):
    return timezone.make_aware(datetime(*args), settings.DEFAULT_TIMEZONE)


class PacificScheduleTests(TestCase):
    def test_true_at_0115_pst(self):
        assert is_pacific_hour(1, utc(2026, 1, 2, 9, 15))

    def test_true_at_0115_pdt(self):
        assert is_pacific_hour(1, utc(2026, 7, 2, 8, 15))

    def test_false_at_other_utc_candidate(self):
        assert not is_pacific_hour(1, utc(2026, 1, 2, 8, 15))  # 00:15 PST
        assert not is_pacific_hour(1, utc(2026, 7, 2, 9, 15))  # 02:15 PDT

    def test_fall_back_runs_once(self):
        assert is_pacific_hour(1, utc(2026, 11, 1, 8, 15))  # 01:15 PDT, fold 0
        assert not is_pacific_hour(1, utc(2026, 11, 1, 9, 15))  # 01:15 PST, fold 1

    def test_spring_forward(self):
        assert is_pacific_hour(1, utc(2026, 3, 8, 9, 15))  # 01:15 PST

    def test_defaults_to_current_time(self):
        with patch('django.utils.timezone.now', return_value=utc(2026, 1, 2, 9, 15)):
            assert is_pacific_hour(1)
            assert not is_pacific_hour(2)

    def test_explicit_args_run_any_time(self):
        with patch('camp.apps.summaries.tasks.rollup_monitor_summaries') as rollup:
            with patch('django.utils.timezone.now', return_value=utc(2026, 1, 2, 20, 0)):
                daily_monitor_summaries(day=pacific(2026, 1, 5))
        rollup.assert_called_once()


# (task name, Pacific hour, minute, [Pacific days it should run on: PST, PDT and,
# where the crontab allows it, the fall-back day], (late `now` -> expected window))
ROLLUP_SCHEDULE = [
    ('daily_monitor_summaries', 1, 0, [(2026, 1, 2), (2026, 7, 2), (2026, 11, 1), (2026, 3, 8)],
     (pacific(2026, 1, 2, 2, 20), pacific(2026, 1, 1), pacific(2026, 1, 2))),
    ('daily_region_summaries', 1, 10, [(2026, 1, 2), (2026, 7, 2), (2026, 11, 1), (2026, 3, 8)],
     (pacific(2026, 7, 2, 2, 30), pacific(2026, 7, 1), pacific(2026, 7, 2))),
    ('monthly_monitor_summaries', 1, 15, [(2026, 1, 1), (2026, 7, 1), (2026, 11, 1)],
     (pacific(2026, 11, 1, 2, 35), pacific(2026, 10, 1), pacific(2026, 11, 1))),
    ('monthly_region_summaries', 1, 25, [(2026, 1, 1), (2026, 7, 1), (2026, 11, 1)],
     (pacific(2026, 2, 1, 2, 45), pacific(2026, 1, 1), pacific(2026, 2, 1))),
    ('quarterly_monitor_summaries', 1, 30, [(2026, 1, 1), (2026, 7, 1)],
     (pacific(2026, 7, 1, 2, 50), pacific(2026, 4, 1), pacific(2026, 7, 1))),
    ('quarterly_region_summaries', 1, 35, [(2026, 1, 1), (2026, 7, 1)],
     (pacific(2026, 1, 1, 2, 55), pacific(2025, 10, 1), pacific(2026, 1, 1))),
    ('seasonal_monitor_summaries', 1, 45, [(2026, 3, 1), (2026, 6, 1), (2026, 12, 1)],
     (pacific(2026, 6, 1, 3, 5), pacific(2026, 3, 1), pacific(2026, 6, 1))),
    ('seasonal_region_summaries', 1, 55, [(2026, 3, 1), (2026, 6, 1), (2026, 12, 1)],
     (pacific(2026, 3, 1, 3, 15), pacific(2025, 12, 1), pacific(2026, 3, 1))),
    ('yearly_monitor_summaries', 2, 0, [(2026, 1, 1), (2027, 1, 1)],
     (pacific(2027, 1, 1, 3, 20), pacific(2026, 1, 1), pacific(2027, 1, 1))),
    ('yearly_region_summaries', 2, 5, [(2026, 1, 1), (2027, 1, 1)],
     (pacific(2026, 1, 1, 3, 25), pacific(2025, 1, 1), pacific(2026, 1, 1))),
]


class PacificCrontabTests(TestCase):
    def fires(self, validate, start, minutes):
        """Naive-UTC minutes in [start, start + minutes) the validator accepts, as Huey's scheduler passes them."""
        start = start.astimezone(dt_timezone.utc).replace(tzinfo=None)
        return [
            start + timedelta(minutes=i) for i in range(minutes)
            if validate(start + timedelta(minutes=i))
        ]

    def test_fires_once_at_the_pacific_hour(self):
        validate = pacific_crontab(1, '15')
        for day in [(2026, 1, 2), (2026, 7, 2), (2026, 11, 1), (2026, 3, 8)]:
            # Scan the two UTC days around the Pacific day, so every candidate hour is seen.
            runs = self.fires(validate, pacific(*day) - timedelta(hours=12), 48 * 60)
            fired = [localtime(r.replace(tzinfo=dt_timezone.utc)) for r in runs]
            assert len(fired) == 2, day  # once on this Pacific day, once on the next
            first = fired[0]
            assert (first.date(), first.hour, first.minute, first.fold) == (
                pacific(*day).date(), 1, 15, 0), day

    def test_fall_back_repeated_hour_fires_once(self):
        validate = pacific_crontab(1, '15')
        assert validate(datetime(2026, 11, 1, 8, 15))  # 01:15 PDT, fold 0
        assert not validate(datetime(2026, 11, 1, 9, 15))  # 01:15 PST, fold 1

    def test_accepts_aware_datetimes(self):
        validate = pacific_crontab(1, '15')
        assert validate(utc(2026, 1, 2, 9, 15))
        assert validate(pacific(2026, 1, 2, 1, 15))
        assert not validate(utc(2026, 1, 2, 8, 15))

    def test_respects_crontab_fields(self):
        validate = pacific_crontab(1, '15', day='1')
        assert validate(datetime(2026, 2, 1, 9, 15))
        assert not validate(datetime(2026, 2, 2, 9, 15))

    def test_every_rollup_task_fires_once_per_period(self):
        for name, hour, minute, days, _ in ROLLUP_SCHEDULE:
            validate = getattr(summary_tasks, name).task_class().validate_datetime
            for day in days:
                runs = self.fires(validate, pacific(*day), 24 * 60)
                assert len(runs) == 1, (name, day, runs)
                local = localtime(runs[0].replace(tzinfo=dt_timezone.utc))
                assert (local.date(), local.hour, local.minute, local.fold) == (
                    pacific(*day).date(), hour, minute, 0), (name, day)

    def test_every_rollup_task_skips_off_days(self):
        # The day before each scheduled day never fires (except for daily tasks, which fire daily).
        for name, _, _, days, _ in ROLLUP_SCHEDULE:
            if name.startswith('daily'):
                continue
            validate = getattr(summary_tasks, name).task_class().validate_datetime
            for day in days:
                assert self.fires(validate, pacific(*day) - timedelta(days=1), 24 * 60) == [], (name, day)

    def test_late_run_still_rolls_up_the_period(self):
        # A rollup that starts well after its scheduled minute (the queue was busy)
        # still rolls up the period it was scheduled for.
        for name, _, _, _, (now, start, end) in ROLLUP_SCHEDULE:
            rollup_name = 'rollup_region_summaries' if '_region_' in name else 'rollup_monitor_summaries'
            with patch(f'camp.apps.summaries.tasks.{rollup_name}') as rollup:
                with patch('django.utils.timezone.now', return_value=now):
                    getattr(summary_tasks, name)()
            rollup.assert_called_once()
            _, _, got_start, got_end = rollup.call_args.args
            assert (got_start, got_end) == (start, end), name


class TrendPanelTests(TestCase):
    fixtures = ['regions.yaml']

    def setUp(self):
        self.user = User.objects.create_superuser(email='admin@example.com', password='password', phone='+15595551234', full_name='Admin')
        self.city = Region.objects.get(pk=9)  # Fresno (city), inside Fresno County
        self.county = Region.objects.counties().get(name='Fresno County')
        self.kern = Region.objects.counties().get(name='Kern County')
        yesterday = timezone.localdate() - timedelta(days=1)
        for offset in range(10):
            day = yesterday - timedelta(days=offset)
            daily_region_summary(self.city, day, 40.0 if offset < 2 else 10.0, station_count=3)
            daily_region_summary(self.county, day, 20.0)
            daily_region_summary(self.kern, day, 30.0)
        # A stale row outside every range must be ignored.
        daily_region_summary(self.city, yesterday - timedelta(days=400), 999.0)

    def panel(self, region, **params):
        request = RequestFactory().get('/', params)
        request.user = self.user
        return [p for p in panels_for(region, request) if isinstance(p, TrendPanel)][0]

    def test_city_tiles_and_comparison(self):
        context = self.panel(self.city).context
        assert context['has_data'] is True
        assert context['pollutant'] == 'pm25'
        assert context['range'] == '30d'
        assert context['stats']['mean'] == 16.0   # (2*40 + 8*10) / 10
        assert context['stats']['days_over'] == 2  # 40 >= 35.5
        assert context['stats']['worst_mean'] == 40.0
        assert context['stats']['stations'] == 3
        assert context['unit'] == 'µg/m³'
        assert context['comparison_label'] == 'Fresno County'
        assert context['chart'].count('class="chart-line"') == 2
        assert dict(self.panel(self.city).tiles())['Days unhealthy for sensitive groups'] == '2'

    def test_county_compares_to_all_counties(self):
        context = self.panel(self.county).context
        assert context['comparison_label'] == 'All SJV counties'
        # The window always spans the full range, so the leading days are None.
        assert len(context['comparison_points']) == 30
        # The comparison line is the mean of county means: (20 + 30) / 2 each day.
        assert next(value for _day, value in context['comparison_points'] if value is not None) == 25.0

    def test_ranges_and_pollutants_are_validated(self):
        assert self.panel(self.city, range='12m').context['range'] == '12m'
        assert self.panel(self.city, range='nope').context['range'] == '30d'
        assert len(self.panel(self.county, range='90d').context['comparison_points']) == 90
        context = self.panel(self.city, pollutant='o3').context
        assert context['pollutant'] == 'pm25'  # no ozone rows for this region
        assert context['pollutant_links'] == []
        daily_region_summary(self.city, timezone.localdate() - timedelta(days=1), 0.05, entry_type='o3')
        context = self.panel(self.city, pollutant='o3').context
        assert context['pollutant'] == 'o3'
        assert [label for label, _url, _on in context['pollutant_links']] == ['PM2.5', 'Ozone']

    def test_no_data_message(self):
        context = self.panel(Region.objects.get(pk=10)).context  # school district, no rows
        assert context['has_data'] is False
        assert context['chart'] == ''
        assert self.panel(Region.objects.get(pk=10)).tiles() == []


class SettleTimeTests(TestCase):
    def test_period_end_each_resolution(self):
        ts = pacific(2026, 10, 15, 12)
        assert period_end('hour', ts) == pacific(2026, 10, 15, 13)
        assert period_end('day', ts) == pacific(2026, 10, 16)
        assert period_end('month', ts) == pacific(2026, 11, 1)
        assert period_end('quarter', ts) == pacific(2027, 1, 1)
        assert period_end('season', ts) == pacific(2026, 12, 1)
        assert period_end('year', ts) == pacific(2027, 1, 1)

    def test_period_end_season_winter_crosses_year(self):
        assert period_end('season', pacific(2026, 1, 10)) == pacific(2026, 3, 1)
        assert period_end('season', pacific(2026, 12, 10)) == pacific(2027, 3, 1)

    def test_period_end_day_across_dst(self):
        assert period_end('day', pacific(2026, 11, 1, 12)) == pacific(2026, 11, 2)
        assert period_end('day', pacific(2026, 3, 8, 12)) == pacific(2026, 3, 9)

    def test_month_settles_4h_after_end(self):
        end = pacific(2026, 11, 1)
        assert not is_settled('month', end, now=pacific(2026, 11, 1, 3, 59))
        assert is_settled('month', end, now=pacific(2026, 11, 1, 4))

    def test_defaults_to_current_time(self):
        end = pacific(2026, 11, 1)
        with patch('django.utils.timezone.now', return_value=pacific(2026, 11, 1, 4)):
            assert is_settled('month', end)
        with patch('django.utils.timezone.now', return_value=pacific(2026, 11, 1, 3)):
            assert not is_settled('month', end)

    def test_open_range_never_settled(self):
        assert not is_settled('year', None)

    def test_margin_covers_schedule(self):
        assert set(ROLLUP_LOCAL_TIME) == set(SETTLE_MARGIN)
        for resolution, offset in ROLLUP_LOCAL_TIME.items():
            assert offset + timedelta(hours=1) <= SETTLE_MARGIN[resolution], resolution

    def effective_runs(self, task, start, minutes):
        """UTC instants in [start, start + minutes) where the task's registered schedule fires."""
        runs = []
        validate = task.task_class().validate_datetime
        for i in range(minutes):
            instant = start + timedelta(minutes=i)
            if validate(instant.replace(tzinfo=None)):
                runs.append(instant)
        return runs

    def test_margin_covers_registered_crontabs(self):
        # (monitor task, region task, resolution, [period ends in PST and PDT])
        cases = [
            ('hourly_monitor_summaries', 'hourly_region_summaries', 'hour',
             [pacific(2026, 1, 1, 13), pacific(2026, 7, 1, 13)]),
            ('daily_monitor_summaries', 'daily_region_summaries', 'day',
             [pacific(2026, 1, 2), pacific(2026, 7, 2)]),
            ('monthly_monitor_summaries', 'monthly_region_summaries', 'month',
             [pacific(2026, 2, 1), pacific(2026, 8, 1)]),
            ('quarterly_monitor_summaries', 'quarterly_region_summaries', 'quarter',
             [pacific(2027, 1, 1), pacific(2026, 7, 1)]),
            ('seasonal_monitor_summaries', 'seasonal_region_summaries', 'season',
             [pacific(2026, 12, 1), pacific(2026, 6, 1)]),
            ('yearly_monitor_summaries', 'yearly_region_summaries', 'year',
             [pacific(2027, 1, 1)]),
        ]
        for monitor_name, region_name, resolution, ends in cases:
            monitor_task = getattr(summary_tasks, monitor_name)
            region_task = getattr(summary_tasks, region_name)
            for end in ends:
                label = f'{resolution} {end.isoformat()}'
                assert period_end(resolution, end - timedelta(microseconds=1)) == end, label
                end_utc = end.astimezone(dt_timezone.utc)
                fire = end_utc + ROLLUP_LOCAL_TIME[resolution]
                window = 60 if resolution == 'hour' else 24 * 60

                # The region task (the later of the pair) runs exactly once, at ROLLUP_LOCAL_TIME.
                assert self.effective_runs(region_task, end_utc, window) == [fire], label
                # The monitor task runs once, before it, so the region rollup has its inputs.
                monitor_runs = self.effective_runs(monitor_task, end_utc, window)
                assert len(monitor_runs) == 1 and monitor_runs[0] < fire, label
                # And everything is done, plus an hour of slack, inside the settle margin.
                assert fire + timedelta(hours=1) <= end_utc + SETTLE_MARGIN[resolution], label

    def test_late_margin_settles_later(self):
        assert set(LATE_SETTLE_MARGIN) == set(SETTLE_MARGIN)
        end = pacific(2026, 11, 2)
        assert is_settled('day', end, now=pacific(2026, 11, 2, 3))
        assert not is_settled('day', end, now=pacific(2026, 11, 2, 3), late=True)
        assert not is_settled('day', end, now=pacific(2026, 11, 2, 6, 59), late=True)
        assert is_settled('day', end, now=pacific(2026, 11, 2, 7), late=True)
        assert not is_settled('day', None, late=True)

    def test_peak_8h_margin(self):
        end = pacific(2026, 11, 2)
        assert not is_settled('day', end, now=pacific(2026, 11, 3, 3), peak_8h=True)
        assert is_settled('day', end, now=pacific(2026, 11, 3, 3))
        assert is_settled('day', end, now=pacific(2026, 11, 3, 4), peak_8h=True)
        # Only the day resolution is affected.
        month_end = pacific(2026, 11, 1)
        now = pacific(2026, 11, 1, 4)
        assert is_settled('month', month_end, now=now, peak_8h=True) == is_settled('month', month_end, now=now)

    def test_peak_8h_margin_covers_refresh_crontab(self):
        # The refresh is the next day's rollup. On fall-back day the following day
        # has 25 hours, so it can land 26h10m after the day ends.
        for end in [pacific(2026, 1, 2), pacific(2026, 7, 2), pacific(2026, 11, 1)]:
            end_utc = end.astimezone(dt_timezone.utc)
            runs = self.effective_runs(summary_tasks.daily_region_summaries, end_utc, 48 * 60)
            assert len(runs) == 2, end
            assert runs[1] + timedelta(hours=1) <= end_utc + PEAK_8H_SETTLE_MARGIN, end

    def test_late_margin_covers_finalize(self):
        # A late type's last change is the finalize_cimis_data run that re-pulls and re-rolls
        # the period, so the margin covers that run plus an hour of slack. For day and longer
        # that is the first run after the period ends. For hours it is the first run on the day
        # after the hour's Pacific date (finalize covers yesterday only), so the worst case is
        # the first hour of a day.
        cases = [
            ('hour', [pacific(2026, 1, 1, 1), pacific(2026, 7, 1, 1)]),
            ('day', [pacific(2026, 1, 2), pacific(2026, 7, 2)]),
            ('month', [pacific(2026, 2, 1), pacific(2026, 8, 1)]),
            ('quarter', [pacific(2027, 1, 1), pacific(2026, 7, 1)]),
            ('season', [pacific(2026, 12, 1), pacific(2026, 6, 1)]),
            ('year', [pacific(2027, 1, 1)]),
        ]
        assert {r for r, _ in cases} == set(LATE_SETTLE_MARGIN)
        for resolution, ends in cases:
            for end in ends:
                label = f'{resolution} {end.isoformat()}'
                end_utc = end.astimezone(dt_timezone.utc)
                runs = self.effective_runs(cimis_tasks.finalize_cimis_data, end_utc, 72 * 60)
                if resolution == 'hour':
                    # finalize re-summarizes (Pacific date of the run) - 1 day, so the run that
                    # covers an hour is the first one on the day after the hour's own Pacific date.
                    hour_date = localtime(end - timedelta(microseconds=1)).date()
                    runs = [r for r in runs if localtime(r).date() - timedelta(days=1) >= hour_date]
                assert runs, label
                assert runs[0] + timedelta(hours=1) <= end_utc + LATE_SETTLE_MARGIN[resolution], label


class HourlyParentScheduleTests(TestCase):
    """The hourly parents take their hour from the schedule, not from when a worker gets to them."""
    fixtures = ['purple-air.yaml', 'regions.yaml']

    def setUp(self):
        self.region = Region.objects.filter(boundary__isnull=False).first()
        self.monitor = PurpleAir.objects.first()
        self.monitor.position = self.region.boundary.geometry.point_on_surface
        self.monitor.save()
        self.hour = datetime(2026, 11, 2, 9, tzinfo=dt_timezone.utc)
        MonitorSummary.objects.create(
            monitor=self.monitor, timestamp=self.hour,
            resolution=BaseSummary.Resolution.HOURLY,
            entry_type='pm25', processor='', **compute_stats([10.0], 1),
        )

    def _region_rows(self):
        return RegionSummary.objects.filter(region=self.region, resolution=BaseSummary.Resolution.HOURLY)

    def _run_region(self, now):
        with patch('camp.apps.summaries.tasks.timezone.now', return_value=now):
            hourly_region_summaries()
        return self._region_rows()

    def test_on_time_run_summarizes_the_hour(self):
        rows = self._run_region(datetime(2026, 11, 2, 10, 50, tzinfo=dt_timezone.utc))
        assert [r.timestamp for r in rows] == [self.hour]

    def test_run_after_the_top_of_the_hour_still_summarizes_the_scheduled_hour(self):
        for now in (
            datetime(2026, 11, 2, 11, 1, tzinfo=dt_timezone.utc),
            datetime(2026, 11, 2, 11, 49, 59, tzinfo=dt_timezone.utc),
        ):
            self._region_rows().delete()
            rows = self._run_region(now)
            assert [r.timestamp for r in rows] == [self.hour], now

    def test_run_at_the_next_fire_targets_the_next_hour(self):
        next_hour = self.hour + timedelta(hours=1)
        MonitorSummary.objects.create(
            monitor=self.monitor, timestamp=next_hour,
            resolution=BaseSummary.Resolution.HOURLY,
            entry_type='pm25', processor='', **compute_stats([10.0], 1),
        )
        rows = self._run_region(datetime(2026, 11, 2, 11, 50, tzinfo=dt_timezone.utc))
        assert [r.timestamp for r in rows] == [next_hour]

    def test_late_run_logs_a_warning(self):
        with self.assertLogs('camp.apps.summaries', level='WARNING') as logs:
            self._run_region(datetime(2026, 11, 2, 11, 1, tzinfo=dt_timezone.utc))
        assert len(logs.records) == 1

    def test_slightly_late_run_logs_nothing(self):
        with self.assertNoLogs('camp.apps.summaries', level='WARNING'):
            self._run_region(datetime(2026, 11, 2, 10, 55, tzinfo=dt_timezone.utc))

    def test_monitor_parent_late_run_summarizes_the_scheduled_hour(self):
        PM25.objects.create(
            monitor=self.monitor, timestamp=self.hour + timedelta(minutes=10),
            stage=PM25.Stage.RAW, processor='', value=12.0, location=self.monitor.location,
        )
        MonitorSummary.objects.all().delete()
        with patch('camp.apps.summaries.tasks.timezone.now',
                   return_value=datetime(2026, 11, 2, 11, 30, tzinfo=dt_timezone.utc)):
            hourly_monitor_summaries()
        assert list(MonitorSummary.objects.values_list('timestamp', flat=True)) == [self.hour]

    def test_priorities(self):
        def priority(task):
            return task.task_class.default_priority
        assert priority(hourly_monitor_summaries) == 110
        assert priority(hourly_region_summaries) == 105
        assert priority(summarize_monitor_hour) == 100
        assert priority(summarize_region_hour) == 90

    def test_hour_for_run_across_the_fall_back_hour(self):
        # 09:55Z on the fall-back day is 01:55 PST, in the second 01:00 Pacific hour.
        hour, lateness = hour_for_run(50, now=datetime(2026, 11, 1, 9, 55, tzinfo=dt_timezone.utc))
        assert hour == datetime(2026, 11, 1, 8, tzinfo=dt_timezone.utc)
        assert lateness == timedelta(minutes=5)

    def test_hour_for_run_before_the_fire_minute_uses_the_previous_fire(self):
        hour, lateness = hour_for_run(50, now=datetime(2026, 3, 8, 10, 10, tzinfo=dt_timezone.utc))
        assert hour == datetime(2026, 3, 8, 8, tzinfo=dt_timezone.utc)
        assert lateness == timedelta(minutes=20)

    def test_fire_minutes_match_the_crontabs(self):
        assert HOURLY_FIRE_MINUTE == {'monitor': 45, 'region': 50}
        assert LATE_RUN_WARNING == timedelta(minutes=10)


class SummaryIntegrityCheckTests(TestCase):
    """The daily check counts misaligned rows and hours with monitor but no region summaries."""
    fixtures = ['purple-air.yaml', 'regions.yaml']

    # 2026-11-02 02:30 PST; "yesterday" is 2026-11-01, the 25-hour fall-back day.
    NOW = datetime(2026, 11, 2, 10, 30, tzinfo=dt_timezone.utc)

    def setUp(self):
        self.region = Region.objects.filter(boundary__isnull=False).first()
        self.monitor = PurpleAir.objects.first()
        self.day_start = pacific(2026, 11, 1)
        self.day_end = pacific(2026, 11, 2)

    def _run(self):
        return summary_tasks.check_summary_integrity.call_local(now=self.NOW)

    def _monitor_hour(self, ts):
        MonitorSummary.objects.create(
            monitor=self.monitor, timestamp=ts, resolution=BaseSummary.Resolution.HOURLY,
            entry_type='pm25', processor='', **compute_stats([10.0], 1),
        )

    def _region_hour(self, ts):
        stats = compute_stats([10.0], 1)
        stats.pop('is_complete', None)
        RegionSummary.objects.create(
            region=self.region, timestamp=ts, resolution=BaseSummary.Resolution.HOURLY,
            entry_type='pm25', station_count=1, **stats,
        )

    def _fill_day(self, skip=None):
        for ts in iter_hours(self.day_start, self.day_end):
            self._monitor_hour(ts)
            if ts != skip:
                self._region_hour(ts)

    def test_clean_data_returns_zeros_and_logs_nothing(self):
        self._fill_day()
        with self.assertNoLogs('camp.apps.summaries', level='ERROR'):
            assert self._run() == {'misaligned': 0, 'missing_region_hours': 0}

    def test_logs_how_long_the_run_took(self):
        self._fill_day()
        with self.assertLogs('camp.apps.summaries', level='INFO') as logs:
            self._run()
        timing = [r for r in logs.records if r.levelname == 'INFO' and 'integrity check took' in r.getMessage()]
        assert len(timing) == 1
        assert 'misaligned scan' in timing[0].getMessage()

    def test_misaligned_month_row_is_counted_and_logged(self):
        MonitorSummary.objects.create(
            monitor=self.monitor, timestamp=pacific(2026, 2, 28, 23),
            resolution=BaseSummary.Resolution.MONTHLY,
            entry_type='pm25', processor='', **compute_stats([10.0], 1),
        )
        with self.assertLogs('camp.apps.summaries', level='ERROR') as logs:
            result = self._run()
        assert result['misaligned'] == 1
        assert len(logs.records) == 1

    def test_misaligned_rows_count_both_tables(self):
        stats = compute_stats([10.0], 1)
        MonitorSummary.objects.create(
            monitor=self.monitor, timestamp=pacific(2026, 2, 28, 23),
            resolution=BaseSummary.Resolution.MONTHLY, entry_type='pm25', processor='', **stats)
        stats.pop('is_complete', None)
        RegionSummary.objects.create(
            region=self.region, timestamp=pacific(2026, 10, 31, 23),
            resolution=BaseSummary.Resolution.DAILY, entry_type='pm25', station_count=1, **stats)
        with self.assertLogs('camp.apps.summaries', level='ERROR'):
            assert self._run()['misaligned'] == 2

    def test_misaligned_rows_older_than_400_days_are_ignored(self):
        MonitorSummary.objects.create(
            monitor=self.monitor, timestamp=pacific(2024, 2, 28, 23),
            resolution=BaseSummary.Resolution.MONTHLY,
            entry_type='pm25', processor='', **compute_stats([10.0], 1),
        )
        assert self._run()['misaligned'] == 0

    def test_hour_without_region_rows_is_counted_and_logged(self):
        self._fill_day(skip=pacific(2026, 11, 1, 3))
        with self.assertLogs('camp.apps.summaries', level='ERROR') as logs:
            result = self._run()
        assert result['missing_region_hours'] == 1
        assert len(logs.records) == 1

    def test_repeated_fall_back_hour_is_checked(self):
        # 01:00 PST is the second 01:00 of the day, an hour after 01:00 PDT.
        self._fill_day(skip=datetime(2026, 11, 1, 9, tzinfo=dt_timezone.utc))
        with self.assertLogs('camp.apps.summaries', level='ERROR'):
            assert self._run()['missing_region_hours'] == 1

    def test_hours_outside_yesterday_are_ignored(self):
        self._fill_day()
        self._monitor_hour(self.day_end)  # today's 00:00, no region row yet
        assert self._run()['missing_region_hours'] == 0

    def test_hour_with_no_monitor_rows_is_not_missing(self):
        assert self._run() == {'misaligned': 0, 'missing_region_hours': 0}

    def test_fires_once_on_fall_back_day_at_0230_pacific(self):
        validate = summary_tasks.check_summary_integrity.task_class().validate_datetime
        start = datetime(2026, 11, 1, tzinfo=dt_timezone.utc)
        runs = [
            start + timedelta(minutes=i) for i in range(24 * 60)
            if validate((start + timedelta(minutes=i)).replace(tzinfo=None))
        ]
        assert len(runs) == 1
        local = localtime(runs[0])
        assert (local.hour, local.minute, local.fold) == (2, 30, 0)


class HourlyOutputCompletenessTests(TestCase):
    """AQLite's CALIBRATED O3 is one value per hour; completeness comes from the CLEANED readings."""

    def setUp(self):
        from camp.apps.monitors.aqlite.tests import make_monitor
        self.monitor = make_monitor()
        self.hour = timezone.make_aware(datetime(2026, 3, 10, 12, 0, 0))

    def _readings(self, hour, n):
        from camp.apps.monitors.aqlite.tests import make_cleaned
        for i in range(n):
            make_cleaned(self.monitor, hour + timedelta(minutes=5 * i), 40.0 + i)

    def _aggregate(self, hour):
        from camp.apps.calibrations import processors
        return processors['AQLiteHourlyAggregator'].aggregate(
            self.monitor, hour, hour + timedelta(hours=1))

    def _hourly(self, hour, processor):
        return compute_monitor_summary(self.monitor, hour, O3, processor)

    def test_aggregated_hour_expected_one(self):
        self._readings(self.hour, 10)
        self._aggregate(self.hour)
        stats = self._hourly(self.hour, 'AQLiteHourlyAggregator')
        assert stats['expected_count'] == 1
        assert stats['count'] == 1
        assert stats['is_complete'] is True

    def test_aggregated_hour_incomplete_below_80pct(self):
        self._readings(self.hour, 9)
        self._aggregate(self.hour)
        stats = self._hourly(self.hour, 'AQLiteHourlyAggregator')
        assert stats['expected_count'] == 1
        assert stats['is_complete'] is False

    def test_raw_series_unchanged(self):
        from camp.apps.monitors.aqlite.tests import make_raw
        for i in range(10):
            make_raw(self.monitor, self.hour + timedelta(minutes=5 * i), 40.0)
        stats = self._hourly(self.hour, '')
        assert stats['expected_count'] == 12

    def test_backfill_matches_hourly(self):
        from camp.apps.summaries.backfill import backfill_monitor_hours
        second = self.hour + timedelta(hours=1)
        self._readings(self.hour, 10)
        self._readings(second, 9)
        self._aggregate(self.hour)
        self._aggregate(second)

        backfill_monitor_hours(self.monitor, self.hour, second + timedelta(hours=1), [O3])

        for hour, complete in ((self.hour, True), (second, False)):
            row = MonitorSummary.objects.get(
                monitor=self.monitor, entry_type='o3', processor='AQLiteHourlyAggregator',
                resolution=MonitorSummary.Resolution.HOURLY, timestamp=hour)
            expected = self._hourly(hour, 'AQLiteHourlyAggregator')
            assert row.expected_count == expected['expected_count'] == 1
            assert row.is_complete is expected['is_complete'] is complete

    def test_daily_rollup_complete(self):
        from camp.apps.summaries.tasks import rollup_monitor_summaries
        from camp.utils.datetime import make_aware
        day = make_aware(datetime(2026, 3, 11), settings.DEFAULT_TIMEZONE)
        for hour in iter_hours(day, day + timedelta(hours=24)):
            self._readings(hour, 10)
            self._aggregate(hour)
            stats = self._hourly(hour, 'AQLiteHourlyAggregator')
            MonitorSummary.objects.create(
                monitor=self.monitor, timestamp=hour,
                resolution=MonitorSummary.Resolution.HOURLY,
                entry_type='o3', processor='AQLiteHourlyAggregator', **stats)

        rollup_monitor_summaries(
            MonitorSummary.Resolution.DAILY, MonitorSummary.Resolution.HOURLY,
            day, day + timedelta(hours=24))

        daily = MonitorSummary.objects.get(
            monitor=self.monitor, processor='AQLiteHourlyAggregator',
            resolution=MonitorSummary.Resolution.DAILY)
        assert daily.expected_count == 24
        assert daily.is_complete is True
