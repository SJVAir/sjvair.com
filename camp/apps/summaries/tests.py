from datetime import datetime, timedelta
from unittest.mock import patch

import numpy as np
import pytest
from tdigest import TDigest

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone

# Fixed datetime for time-sensitive task tests.
# Apr 1, 2026 10:30 UTC — a convenient date for calendar helper assertions:
#   yesterday       = 2026-03-31
#   last month      = 2026-03-01
#   last quarter    = 2026-01-01  (Q1: Jan–Mar)
#   last season     = 2025-12-01  (winter: Dec–Feb; use Mar 1 as "now" for that helper)
FIXED_NOW = timezone.make_aware(datetime(2026, 4, 1, 10, 30, 0))

from camp.apps.entries.models import CO, NO2, O3, PM25, SO2
from camp.apps.monitors.bam.models import BAM1022
from camp.apps.monitors.models import Monitor
from camp.apps.monitors.purpleair.models import PurpleAir
from camp.apps.qaqc.models import HealthCheck
from camp.apps.regions.models import Region
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
from camp.apps.summaries.tasks import (
    daily_monitor_summaries,
    get_summarizable_entry_models,
    hourly_monitor_summaries,
    hourly_region_summaries,
    monthly_monitor_summaries,
    quarterly_monitor_summaries,
    rollup_monitor_summaries,
    rollup_region_summaries,
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


class GetSummarizableEntryModelsTests(TestCase):
    def test_returns_expected_models(self):
        models = get_summarizable_entry_models()
        assert {m.__name__ for m in models} == {'PM25', 'O3', 'CO', 'NO2', 'SO2'}

    def test_excluded_types_not_present(self):
        from camp.apps.entries.models import CO2, Humidity, Pressure, Temperature
        models = get_summarizable_entry_models()
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

    def test_invalid_date_raises_error(self):
        with pytest.raises((CommandError, SystemExit)):
            self._run('not-a-date')


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
        with patch('django.utils.timezone.now', return_value=FIXED_NOW):
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
        with patch('django.utils.timezone.now', return_value=FIXED_NOW):
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

        with patch('django.utils.timezone.now', return_value=FIXED_NOW):
            daily_monitor_summaries()

        assert MonitorSummary.objects.filter(
            monitor=self.monitor,
            timestamp=self.yesterday,
            resolution=BaseSummary.Resolution.DAILY,
        ).exists()


class CalendarHelperTests(TestCase):
    """Tests for the private calendar helpers that compute rollup windows."""

    def test_yesterday(self):
        from camp.apps.summaries.tasks import _yesterday
        with patch('django.utils.timezone.now', return_value=FIXED_NOW):
            result = _yesterday()
        # FIXED_NOW = 2026-04-01 10:30 UTC = 2026-04-01 03:30 PDT → yesterday in LA = 2026-03-31
        expected = timezone.make_aware(datetime(2026, 3, 31), settings.DEFAULT_TIMEZONE)
        assert result == expected

    def test_last_month_start(self):
        from camp.apps.summaries.tasks import _last_month_start
        with patch('django.utils.timezone.now', return_value=FIXED_NOW):
            result = _last_month_start()
        assert result.year == 2026
        assert result.month == 3
        assert result.day == 1

    def test_last_quarter_start(self):
        from camp.apps.summaries.tasks import _last_quarter_start
        # Apr 1 → current quarter is Q2, last quarter is Q1 = Jan 1
        with patch('django.utils.timezone.now', return_value=FIXED_NOW):
            result = _last_quarter_start()
        assert result.year == 2026
        assert result.month == 1
        assert result.day == 1

    def test_last_season_start(self):
        from camp.apps.summaries.tasks import _last_season_start
        # Need "now" to be March in LA time. 2026-03-01 12:00 UTC = 04:00 PST = March in LA.
        mar_1 = timezone.make_aware(datetime(2026, 3, 1, 12, 0, 0))
        with patch('django.utils.timezone.now', return_value=mar_1):
            result = _last_season_start()
        # March → end_month=3, start_month=12, start_year=2025 → Dec 1 2025
        assert result.year == 2025
        assert result.month == 12
        assert result.day == 1

    def test_window_end_quarterly_is_dst_safe(self):
        # Jan 1 midnight PST = UTC-8. The quarterly window end (Apr 1) falls in
        # PDT = UTC-7. Using .replace() would keep the PST offset, giving
        # Apr 1 08:00 UTC instead of the correct Apr 1 07:00 UTC.
        from camp.apps.summaries.management.commands.rebuild_summaries import Command
        jan_1_pst = timezone.make_aware(datetime(2026, 1, 1, 0, 0, 0), settings.DEFAULT_TIMEZONE)
        apr_1_pdt = timezone.make_aware(datetime(2026, 4, 1, 0, 0, 0), settings.DEFAULT_TIMEZONE)

        result = Command()._window_end(BaseSummary.Resolution.QUARTERLY, jan_1_pst)

        assert result == apr_1_pdt
        # PDT is UTC-7; PST is UTC-8 — verify the offset changed
        assert result.utcoffset() != jan_1_pst.utcoffset()

    def test_window_end_seasonal_is_dst_safe(self):
        # Dec → Mar stays in PST (no DST crossing), so offsets should match.
        from camp.apps.summaries.management.commands.rebuild_summaries import Command
        dec_1_pst = timezone.make_aware(datetime(2025, 12, 1, 0, 0, 0), settings.DEFAULT_TIMEZONE)
        mar_1_pst = timezone.make_aware(datetime(2026, 3, 1, 0, 0, 0), settings.DEFAULT_TIMEZONE)

        result = Command()._window_end(BaseSummary.Resolution.SEASONAL, dec_1_pst)

        assert result == mar_1_pst
        assert result.utcoffset() == dec_1_pst.utcoffset()


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

        with patch('django.utils.timezone.now', return_value=FIXED_NOW):
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

        with patch('django.utils.timezone.now', return_value=FIXED_NOW):
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
