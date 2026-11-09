from datetime import datetime, timedelta
from io import StringIO
from unittest.mock import patch

from django.conf import settings
from django.contrib.gis.geos import Point
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
import pytest
from tdigest import TDigest

from camp.apps.entries import models as entries
from camp.apps.monitors.airnow.models import AirNow
from camp.apps.monitors.purpleair.models import PurpleAir
from camp.apps.regions.models import Region
from camp.apps.summaries.aggregators import tdigest_to_dict
from camp.apps.summaries.models import BaseSummary, MonitorSummary, RegionSummary
from camp.apps.summaries.peaks import (
    FillResult, day_hours, fill_daily_peaks, max_1h, max_8h, mean_24h, peak_entry_models,
    standard_for,
)
from camp.apps.summaries.tasks import (
    daily_monitor_summaries, daily_region_summaries,
    rollup_monitor_summaries, rollup_region_summaries,
)
from camp.utils.datetime import make_aware


def day(y, m, d):
    return day_hours(make_aware(datetime(y, m, d), settings.DEFAULT_TIMEZONE))


def series(hours, values, start=0):
    return {hours[start + i]: v for i, v in enumerate(values)}


class PeakMathTests(TestCase):
    def test_max_1h_full_day(self):
        hours = day(2026, 7, 1)
        hourly = series(hours, [10.0] * 23 + [130.0])
        assert max_1h(hours, hourly, 125) == 130.0

    def test_max_1h_threshold(self):
        hours = day(2026, 7, 1)
        assert max_1h(hours, series(hours, [50.0] * 18), 125) == 50.0
        assert max_1h(hours, series(hours, [50.0] * 17), 125) is None

    def test_max_1h_short_day_over_standard(self):
        hours = day(2026, 7, 1)
        assert max_1h(hours, series(hours, [1, 2, 125, 3, 4]), 125) == 125.0
        assert max_1h(hours, series(hours, [1, 2, 124.9, 3, 4]), 125) is None

    def test_max_1h_dst_days(self):
        spring = day(2026, 3, 8)
        assert len(spring) == 23
        assert max_1h(spring, series(spring, [5.0] * 18), 125) == 5.0
        assert max_1h(spring, series(spring, [5.0] * 17), 125) is None
        fall = day(2026, 11, 1)
        assert len(fall) == 25
        assert max_1h(fall, series(fall, [5.0] * 19), 125) == 5.0
        assert max_1h(fall, series(fall, [5.0] * 18), 125) is None

    def test_zero_and_negative_count_as_data(self):
        hours = day(2026, 7, 1)
        hourly = series(hours, [-0.5] * 9 + [0.0] * 9)
        assert max_1h(hours, hourly, 125) == 0.0

    def test_max_8h_window_validity(self):
        hours = day(2026, 7, 1)
        # Only 6 hours at 10 starting at 00:00: window 0 averages those 6.
        hourly = series(hours, [10.0] * 6)
        assert max_8h(hours, hourly, 9.5) == 10.0
        # 5 hours: no valid window.
        assert max_8h(hours, series(hours, [10.0] * 5), 9.5) is None

    def test_max_8h_threshold(self):
        hours = day(2026, 7, 1)
        # Data in hours 0..22: a window needs >= 6 hours, so windows 0..17 (18) are valid.
        assert max_8h(hours, series(hours, [1.0] * 23), 9.5) == 1.0
        # Data in hours 0..21: windows 0..16 (17) are valid, under the 75% rule.
        assert max_8h(hours, series(hours, [1.0] * 22), 9.5) is None
        # Still 17 windows, but the peak meets the standard.
        hourly = series(hours, [1.0] * 14 + [20.0] * 8)
        assert max_8h(hours, hourly, 9.5) == 20.0

    def test_max_8h_uses_next_day(self):
        hours = day(2026, 7, 1)
        nxt = day(2026, 7, 2)
        hourly = series(hours, [1.0] * 24)
        base = max_8h(hours, hourly, 9.5)
        for h in nxt[:7]:
            hourly[h] = 20.0
        raised = max_8h(hours, hourly, 9.5)
        assert base == 1.0
        # Only the window starting 23:00 holds the seven 20.0 hours, plus one 1.0.
        assert raised == 17.625

    def test_max_8h_missing_next_day(self):
        hours = day(2026, 7, 1)
        # A full day and no next-day hours: windows 0..18 have >= 6 hours (19 valid).
        assert max_8h(hours, series(hours, [2.0] * 24), 9.5) == 2.0
        # Hours 3..23: windows 1..18 are valid (18, the threshold). Windows 19..23 have
        # under 6 hours, so their 9.0 averages don't count; window 18 holds one 1.0 and
        # five 9.0.
        hourly = series(hours, [1.0] * 16 + [9.0] * 5, start=3)
        assert max_8h(hours, hourly, 9.5) == pytest.approx(46 / 6)
        # Hours 4..23: 17 valid windows, under the 75% rule.
        hourly = series(hours, [1.0] * 15 + [9.0] * 5, start=4)
        assert max_8h(hours, hourly, 9.5) is None

    def test_mean_24h_threshold(self):
        hours = day(2026, 7, 1)
        assert mean_24h(hours, series(hours, [10.0] * 17 + [28.0])) == 11.0
        assert mean_24h(hours, series(hours, [10.0] * 17)) is None
        spring = day(2026, 3, 8)
        assert mean_24h(spring, series(spring, [5.0] * 18)) == 5.0
        assert mean_24h(spring, series(spring, [5.0] * 17)) is None
        fall = day(2026, 11, 1)
        assert mean_24h(fall, series(fall, [5.0] * 19)) == 5.0
        assert mean_24h(fall, series(fall, [5.0] * 18)) is None

    def test_mean_24h_no_standard_exception(self):
        hours = day(2026, 7, 1)
        assert mean_24h(hours, series(hours, [500.0] * 5)) is None

    def test_mean_24h_is_mean_of_hourly_means(self):
        hours = day(2026, 7, 1)
        hourly = series(hours, [10.0, 30.0] * 9)
        assert mean_24h(hours, hourly) == 20.0

    def test_peak_entry_models(self):
        assert peak_entry_models() == {
            entries.O3: 'max_1h',
            entries.NO2: 'max_1h',
            entries.SO2: 'max_1h',
            entries.CO: 'max_8h',
            entries.PM25: 'mean_24h',
            entries.PM100: 'mean_24h',
        }

    def test_standard_for(self):
        assert standard_for(entries.CO) == 9.5
        assert standard_for(entries.O3) == 125.0


R = BaseSummary.Resolution


def pacific_day(y, m, d):
    return make_aware(datetime(y, m, d), settings.DEFAULT_TIMEZONE)


def _stats(mean):
    digest = TDigest()
    digest.update(mean)
    return dict(
        count=1, expected_count=1, sum_value=mean, sum_of_squares=mean * mean,
        tdigest=tdigest_to_dict(digest), minimum=mean, maximum=mean, mean=mean,
        stddev=0.0, p25=mean, p75=mean,
    )


class FillDailyPeaksTests(TestCase):
    fixtures = ['purple-air.yaml', 'regions.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.first()
        self.region = Region.objects.filter(boundary__isnull=False).first()
        self.day = pacific_day(2026, 7, 1)
        self.next_day = pacific_day(2026, 7, 2)
        self.hours = day_hours(self.day)

    def monitor_hours(self, entry_type, values, processor='', is_complete=True, start=0):
        for i, v in enumerate(values):
            MonitorSummary.objects.create(
                monitor=self.monitor, timestamp=self.hours[start + i], resolution=R.HOURLY,
                entry_type=entry_type, processor=processor, is_complete=is_complete, **_stats(v),
            )

    def monitor_daily(self, entry_type, processor='', resolution=R.DAILY, timestamp=None):
        return MonitorSummary.objects.create(
            monitor=self.monitor, timestamp=timestamp or self.day, resolution=resolution,
            entry_type=entry_type, processor=processor, is_complete=True, **_stats(1.0),
        )

    def region_hours(self, entry_type, values):
        for i, v in enumerate(values):
            RegionSummary.objects.create(
                region=self.region, timestamp=self.hours[i], resolution=R.HOURLY,
                entry_type=entry_type, station_count=1, weight=1.0, **_stats(v),
            )

    def region_daily(self, entry_type, resolution=R.DAILY, timestamp=None):
        return RegionSummary.objects.create(
            region=self.region, timestamp=timestamp or self.day, resolution=resolution,
            entry_type=entry_type, station_count=1, weight=1.0, **_stats(1.0),
        )

    def fill(self, kind='monitor', **kwargs):
        ids = [self.monitor.pk] if kind == 'monitor' else [self.region.pk]
        return fill_daily_peaks(kind, ids, self.day, self.next_day, **kwargs)

    def test_sentinel_hour_not_data(self):
        self.monitor_hours('o3', [50.0] * 8 + [-999.0] + [50.0] * 9)
        row = self.monitor_daily('o3')
        result = self.fill()
        row.refresh_from_db()
        assert row.max_1h is None  # 17 valid hours, 18 needed
        assert result.skipped == 1

    def test_sentinel_not_in_8h_average(self):
        self.monitor_hours('co', [4.0] * 24)
        MonitorSummary.objects.filter(
            resolution=R.HOURLY, entry_type='co', timestamp=self.hours[3]).update(mean=-999.0)
        row = self.monitor_daily('co')
        result = self.fill()
        row.refresh_from_db()
        assert row.max_8h == 4.0
        assert result.skipped == 1

    def test_sentinel_boundary(self):
        self.monitor_hours('o3', [-900.0] + [-899.9] + [20.0] * 22)
        row = self.monitor_daily('o3')
        result = self.fill()
        row.refresh_from_db()
        assert result.skipped == 1
        assert row.max_1h == 20.0

    def test_rollup_logs_skips(self):
        self.monitor_hours('o3', [50.0] * 23 + [-999.0])
        with self.assertLogs('camp.apps.summaries', 'WARNING') as logs:
            rollup_monitor_summaries(R.DAILY, R.HOURLY, self.day, self.next_day)
        assert any('1' in m and 'sentinel' in m for m in logs.output)

    def test_rollup_no_warning_without_skips(self):
        self.monitor_hours('o3', [50.0] * 24)
        with self.assertNoLogs('camp.apps.summaries', 'WARNING'):
            rollup_monitor_summaries(R.DAILY, R.HOURLY, self.day, self.next_day)

    def test_fills_monitor_o3(self):
        self.monitor_hours('o3', [10.0] * 23 + [130.0])
        row = self.monitor_daily('o3')
        assert self.fill().updated == {'o3': 1}
        row.refresh_from_db()
        assert row.max_1h == 130.0
        assert row.max_8h is None

    def test_incomplete_hours_ignored(self):
        self.monitor_hours('o3', [50.0] * 17 + [60.0])
        self.monitor_hours('o3', [120.0] * 6, is_complete=False, start=18)
        row = self.monitor_daily('o3')
        self.fill()
        row.refresh_from_db()
        assert row.max_1h == 60.0

    def test_region_rows(self):
        self.region_hours('o3', [10.0] * 23 + [130.0])
        row = self.region_daily('o3')
        assert self.fill('region').updated == {'o3': 1}
        row.refresh_from_db()
        assert row.max_1h == 130.0
        assert row.max_8h is None

    def test_co_gets_max_8h_only(self):
        self.monitor_hours('co', [2.0] * 24)
        row = self.monitor_daily('co')
        self.fill()
        row.refresh_from_db()
        assert row.max_8h == 2.0
        assert row.max_1h is None

    def test_fills_pm25_mean_24h(self):
        self.monitor_hours('pm25', [10.0] * 23 + [34.0])
        row = self.monitor_daily('pm25')
        assert self.fill().updated == {'pm25': 1}
        row.refresh_from_db()
        assert row.mean_24h == 11.0
        assert row.max_1h is None
        assert row.max_8h is None

    def test_o3_keeps_mean_24h_null(self):
        self.monitor_hours('o3', [10.0] * 24)
        row = self.monitor_daily('o3')
        self.fill()
        row.refresh_from_db()
        assert row.mean_24h is None

    def test_region_mean_24h(self):
        self.region_hours('pm25', [10.0] * 23 + [34.0])
        row = self.region_daily('pm25')
        assert self.fill('region').updated == {'pm25': 1}
        row.refresh_from_db()
        assert row.mean_24h == 11.0

    def test_nine_hour_day_has_no_mean_24h(self):
        self.monitor_hours('pm25', [5.0] * 9)
        row = self.monitor_daily('pm25')
        self.fill()
        row.refresh_from_db()
        assert row.mean_24h is None
        assert row.mean == 1.0
        assert row.is_complete

    def test_peaks_per_processor(self):
        self.monitor_hours('o3', [10.0] * 23 + [200.0], processor='')
        self.monitor_hours('o3', [10.0] * 23 + [90.0], processor='AQLiteHourlyAggregator')
        raw = self.monitor_daily('o3', processor='')
        cal = self.monitor_daily('o3', processor='AQLiteHourlyAggregator')
        assert self.fill().updated == {'o3': 2}
        raw.refresh_from_db()
        cal.refresh_from_db()
        assert raw.max_1h == 200.0
        assert cal.max_1h == 90.0

    def test_fields_subset(self):
        self.monitor_hours('o3', [10.0] * 23 + [130.0])
        row = self.monitor_daily('o3')
        MonitorSummary.objects.filter(pk=row.pk).update(max_1h=42.0)
        self.fill(fields=('max_8h',))
        row.refresh_from_db()
        assert row.max_1h == 42.0
        assert row.max_8h is None

    def test_dry_run_writes_nothing(self):
        self.monitor_hours('o3', [10.0] * 23 + [130.0])
        row = self.monitor_daily('o3')
        assert self.fill(dry_run=True).updated == {'o3': 1}
        row.refresh_from_db()
        assert row.max_1h is None

    def test_entry_models_subset_and_progress(self):
        self.monitor_hours('o3', [10.0] * 24)
        self.monitor_hours('co', [2.0] * 24)
        o3 = self.monitor_daily('o3')
        co = self.monitor_daily('co')
        messages = []
        result = self.fill(entry_models=[entries.CO], progress=messages.append)
        assert result.updated == {'co': 1}
        o3.refresh_from_db()
        co.refresh_from_db()
        assert o3.max_1h is None
        assert co.max_8h == 2.0
        assert len(messages) == 1

    def test_refill_clears_when_coverage_drops(self):
        self.monitor_hours('o3', [10.0] * 23 + [100.0])
        row = self.monitor_daily('o3')
        self.fill()
        row.refresh_from_db()
        assert row.max_1h == 100.0
        # 7 hours turn incomplete: 17 of 24 left, and 100 is under the standard.
        MonitorSummary.objects.filter(
            resolution=R.HOURLY, entry_type='o3', timestamp__in=self.hours[:7],
        ).update(is_complete=False)
        assert self.fill().updated == {'o3': 1}
        row.refresh_from_db()
        assert row.max_1h is None

    def test_stale_max_1h_on_co_cleared(self):
        self.monitor_hours('co', [2.0] * 24)
        row = self.monitor_daily('co')
        MonitorSummary.objects.filter(pk=row.pk).update(max_1h=5.0)
        assert self.fill().updated == {'co': 1}
        row.refresh_from_db()
        assert row.max_1h is None
        assert row.max_8h == 2.0

    def test_unchanged_rows_not_counted(self):
        self.monitor_hours('o3', [10.0] * 24)
        self.monitor_daily('o3')
        assert self.fill().updated == {'o3': 1}
        assert self.fill().updated == {}

    def test_rollup_fills_peaks(self):
        self.monitor_hours('o3', [10.0] * 23 + [130.0])
        rollup_monitor_summaries(R.DAILY, R.HOURLY, self.day, self.next_day)
        daily = MonitorSummary.objects.get(resolution=R.DAILY, entry_type='o3')
        assert daily.max_1h == 130.0
        rollup_monitor_summaries(R.MONTHLY, R.DAILY, pacific_day(2026, 7, 1), pacific_day(2026, 8, 1))
        monthly = MonitorSummary.objects.get(resolution=R.MONTHLY, entry_type='o3')
        assert monthly.max_1h is None
        assert monthly.max_8h is None

        self.region_hours('o3', [10.0] * 23 + [130.0])
        rollup_region_summaries(R.DAILY, R.HOURLY, self.day, self.next_day)
        daily = RegionSummary.objects.get(resolution=R.DAILY, entry_type='o3')
        assert daily.max_1h == 130.0
        rollup_region_summaries(R.MONTHLY, R.DAILY, pacific_day(2026, 7, 1), pacific_day(2026, 8, 1))
        monthly = RegionSummary.objects.get(resolution=R.MONTHLY, entry_type='o3')
        assert monthly.max_1h is None
        assert monthly.max_8h is None

    def test_reroll_keeps_and_refreshes_peaks(self):
        self.monitor_hours('o3', [10.0] * 23 + [130.0])
        rollup_monitor_summaries(R.DAILY, R.HOURLY, self.day, self.next_day)
        daily = MonitorSummary.objects.get(resolution=R.DAILY, entry_type='o3')
        assert daily.max_1h == 130.0

        # The upsert alone (fill skipped) leaves the peak in place.
        with patch('camp.apps.summaries.tasks.fill_daily_peaks', return_value=FillResult({}, 0)) as fill:
            rollup_monitor_summaries(R.DAILY, R.HOURLY, self.day, self.next_day)
        assert fill.called
        daily.refresh_from_db()
        assert daily.max_1h == 130.0

        MonitorSummary.objects.filter(
            resolution=R.HOURLY, entry_type='o3', timestamp=self.hours[5],
        ).update(mean=150.0)
        rollup_monitor_summaries(R.DAILY, R.HOURLY, self.day, self.next_day)
        daily.refresh_from_db()
        assert daily.max_1h == 150.0

        # The same for regions.
        self.region_hours('o3', [10.0] * 23 + [130.0])
        rollup_region_summaries(R.DAILY, R.HOURLY, self.day, self.next_day)
        with patch('camp.apps.summaries.tasks.fill_daily_peaks', return_value=FillResult({}, 0)):
            rollup_region_summaries(R.DAILY, R.HOURLY, self.day, self.next_day)
        region_daily = RegionSummary.objects.get(resolution=R.DAILY, entry_type='o3')
        assert region_daily.max_1h == 130.0


class FillDailyPeaksQueryTests(TestCase):
    """Owners are read in groups, so the query count doesn't grow per owner."""

    def setUp(self):
        self.day = pacific_day(2026, 7, 1)
        self.next_day = pacific_day(2026, 7, 2)
        self.hours = day_hours(self.day)

    def make_monitors(self, n):
        monitors = []
        for i in range(n):
            monitor = AirNow.objects.create(
                name=f'AN {i}', position=Point(-119.5, 36.5, srid=4326), location='outside')
            for hour in self.hours:
                MonitorSummary.objects.create(
                    monitor=monitor, timestamp=hour, resolution=R.HOURLY, entry_type='o3',
                    processor='', is_complete=True, **_stats(10.0))
            # Each monitor gets its own peak, so a mixed-up series shows.
            MonitorSummary.objects.filter(
                monitor=monitor, resolution=R.HOURLY, timestamp=self.hours[12],
            ).update(mean=50.0 + i)
            MonitorSummary.objects.create(
                monitor=monitor, timestamp=self.day, resolution=R.DAILY, entry_type='o3',
                processor='', is_complete=True, **_stats(1.0))
            monitors.append(monitor)
        return monitors

    def queries(self, ids):
        with CaptureQueriesContext(connection) as ctx:
            result = fill_daily_peaks('monitor', ids, self.day, self.next_day, dry_run=True)
        return len(ctx.captured_queries), result.updated

    def test_query_count_bounded(self):
        monitors = self.make_monitors(6)
        # Owner list, then one daily-rows and one hourly query for the one group.
        assert self.queries(None) == (3, {'o3': 6})
        assert self.queries([m.pk for m in monitors[:2]]) == (3, {'o3': 2})
        assert self.queries([m.pk for m in monitors]) == (3, {'o3': 6})

    def test_groups_keep_series_apart(self):
        monitors = self.make_monitors(5)
        with patch('camp.apps.summaries.peaks.OWNER_GROUP_SIZE', 2):
            n, result = self.queries(None)
            assert n == 1 + 3 * 2
            assert result == {'o3': 5}
            fill_daily_peaks('monitor', None, self.day, self.next_day)
        for i, monitor in enumerate(monitors):
            row = MonitorSummary.objects.get(monitor=monitor, resolution=R.DAILY)
            assert row.max_1h == 50.0 + i


class NextNightRefreshTests(TestCase):
    """The next day's daily task recomputes the previous day's max_8h."""
    fixtures = FillDailyPeaksTests.fixtures
    setUp = FillDailyPeaksTests.setUp
    monitor_hours = FillDailyPeaksTests.monitor_hours
    region_hours = FillDailyPeaksTests.region_hours

    def _provisional_then_morning(self, make_hours, daily_model, **owner):
        make_hours('co', [1.0] * 24)
        # Day D-1 rolled before D's morning hours existed.
        rollup = rollup_monitor_summaries if daily_model is MonitorSummary else rollup_region_summaries
        rollup(R.DAILY, R.HOURLY, self.day, self.next_day)
        row = daily_model.objects.get(resolution=R.DAILY, entry_type='co', timestamp=self.day, **owner)
        provisional = row.max_8h
        # D's morning arrives: the windows that start late on D-1 now see 20s.
        nxt = day_hours(self.next_day)
        model = MonitorSummary if daily_model is MonitorSummary else RegionSummary
        for i in range(8):
            extra = dict(monitor=self.monitor, processor='', is_complete=True) if model is MonitorSummary \
                else dict(region=self.region, station_count=1, weight=1.0)
            model.objects.create(
                timestamp=nxt[i], resolution=R.HOURLY, entry_type='co', **extra, **_stats(20.0))
        return row, provisional

    def test_daily_task_refreshes_previous_max_8h_monitor(self):
        row, provisional = self._provisional_then_morning(
            self.monitor_hours, MonitorSummary, monitor=self.monitor)
        assert provisional == 1.0
        daily_monitor_summaries(day=self.next_day)
        row.refresh_from_db()
        assert row.max_8h == 17.625  # window from 23:00: one 1.0 hour and seven 20.0 hours

    def test_daily_task_refreshes_previous_max_8h_region(self):
        row, provisional = self._provisional_then_morning(
            self.region_hours, RegionSummary, region=self.region)
        assert provisional == 1.0
        daily_region_summaries(day=self.next_day)
        row.refresh_from_db()
        assert row.max_8h == 17.625

    def test_default_day_refreshes_previous_and_rolls_yesterday(self):
        # Scheduler path: no argument. At 01:00 Pacific on D+1 the task rolls D
        # and refreshes D-1, resolving the day once.
        d_prev, d, d_next = self.day, self.next_day, pacific_day(2026, 7, 3)
        self.monitor_hours('co', [1.0] * 24)
        self.region_hours('co', [1.0] * 24)
        rollup_monitor_summaries(R.DAILY, R.HOURLY, d_prev, d)
        rollup_region_summaries(R.DAILY, R.HOURLY, d_prev, d)
        for i, hour in enumerate(day_hours(d)):
            if i < 8:
                MonitorSummary.objects.create(
                    monitor=self.monitor, timestamp=hour, resolution=R.HOURLY, entry_type='co',
                    processor='', is_complete=True, **_stats(20.0))
                RegionSummary.objects.create(
                    region=self.region, timestamp=hour, resolution=R.HOURLY, entry_type='co',
                    station_count=1, weight=1.0, **_stats(20.0))
        now = d_next + timedelta(hours=1, minutes=5)
        with patch('django.utils.timezone.now', return_value=now):
            daily_monitor_summaries()
            daily_region_summaries()
        for model, owner in ((MonitorSummary, {'monitor': self.monitor}), (RegionSummary, {'region': self.region})):
            prev = model.objects.get(resolution=R.DAILY, entry_type='co', timestamp=d_prev, **owner)
            assert prev.max_8h == 17.625
            assert model.objects.filter(resolution=R.DAILY, entry_type='co', timestamp=d, **owner).exists()


class FillDailyPeaksCommandTests(TestCase):
    fixtures = ['purple-air.yaml', 'regions.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.first()
        self.day = pacific_day(2026, 7, 1)
        self.hours = day_hours(self.day)

    def run_command(self, *args):
        out = StringIO()
        call_command('fill_daily_peaks', *args, stdout=out)
        return out.getvalue()

    def hourly(self, monitor, entry_type, values, hours):
        for hour, v in zip(hours, values):
            MonitorSummary.objects.create(
                monitor=monitor, timestamp=hour, resolution=R.HOURLY,
                entry_type=entry_type, processor='', is_complete=True, **_stats(v),
            )

    def daily(self, monitor, entry_type, day):
        return MonitorSummary.objects.create(
            monitor=monitor, timestamp=day, resolution=R.DAILY,
            entry_type=entry_type, processor='', is_complete=True, **_stats(1.0),
        )

    def o3_day(self, monitor=None, day=None):
        monitor = monitor or self.monitor
        day = day or self.day
        self.hourly(monitor, 'o3', [10.0] * 23 + [130.0], day_hours(day))
        return self.daily(monitor, 'o3', day)

    def test_requires_scope(self):
        with self.assertRaises(CommandError):
            self.run_command('2026-07-01', '2026-07-02')

    def test_start_before_end(self):
        with self.assertRaises(CommandError):
            self.run_command('2026-07-02', '2026-07-02', '--monitor', str(self.monitor.pk))

    def test_rejects_non_positive_batch_size(self):
        for value in ('0', '-5'):
            with self.assertRaises(CommandError):
                self.run_command('2026-07-01', '2026-07-02', '--monitor', str(self.monitor.pk),
                                 '--batch-size', value)

    def test_region_scopes(self):
        region = Region.objects.filter(boundary__isnull=False).first()
        for hour, v in zip(self.hours, [10.0] * 23 + [130.0]):
            RegionSummary.objects.create(
                region=region, timestamp=hour, resolution=R.HOURLY, entry_type='o3',
                station_count=1, weight=1.0, **_stats(v))
        row = RegionSummary.objects.create(
            region=region, timestamp=self.day, resolution=R.DAILY, entry_type='o3',
            station_count=1, weight=1.0, **_stats(1.0))

        out = self.run_command('2026-07-01', '2026-07-02', '--region', str(region.pk), '--dry-run')
        assert 'region o3: 1 row would change' in out
        out = self.run_command('2026-07-01', '2026-07-02', '--region', str(region.pk))
        assert 'region o3: 1 row changed' in out
        row.refresh_from_db()
        assert row.max_1h == 130.0

        RegionSummary.objects.filter(pk=row.pk).update(max_1h=None)
        out = self.run_command('2026-07-01', '2026-07-02', '--region-type', region.type)
        assert 'region o3: 1 row changed' in out
        row.refresh_from_db()
        assert row.max_1h == 130.0

    def test_rejects_non_peak_entry_type(self):
        with self.assertRaises(CommandError) as ctx:
            self.run_command('2026-07-01', '2026-07-02', '--monitor', str(self.monitor.pk),
                             '--entry-type', 'temperature')
        message = str(ctx.exception)
        assert 'o3' in message and 'co' in message

    def test_dry_run_counts(self):
        row = self.o3_day()
        out = self.run_command('2026-07-01', '2026-07-02', '--monitor', str(self.monitor.pk), '--dry-run')
        assert 'o3: 1 row would change' in out
        row.refresh_from_db()
        assert row.max_1h is None

    def test_fills_and_is_idempotent(self):
        row = self.o3_day()
        args = ('2026-07-01', '2026-07-02', '--monitor', str(self.monitor.pk))
        out = self.run_command(*args)
        assert 'o3: 1 row changed' in out
        row.refresh_from_db()
        assert row.max_1h == 130.0
        assert row.max_8h is None
        before = MonitorSummary.objects.values().get(pk=row.pk)

        out = self.run_command(*args)
        assert 'nothing to do' in out
        assert MonitorSummary.objects.values().get(pk=row.pk) == before

        row.refresh_from_db()
        assert row.mean == 1.0
        assert row.maximum == 1.0
        assert row.is_complete

    def test_monitor_type_scope(self):
        purple = self.o3_day()
        airnow = AirNow.objects.create(
            name='AN', position=Point(-119.5, 36.5, srid=4326), location='outside')
        other = self.o3_day(airnow)
        self.run_command('2026-07-01', '2026-07-02', '--monitor-type', 'airnow')
        purple.refresh_from_db()
        other.refresh_from_db()
        assert other.max_1h == 130.0
        assert purple.max_1h is None

    def test_range_spanning_two_months(self):
        june = self.o3_day(day=pacific_day(2026, 6, 30))
        july = self.o3_day(day=pacific_day(2026, 7, 1))
        out = self.run_command('2026-06-30', '2026-07-02', '--monitor', str(self.monitor.pk))
        june.refresh_from_db()
        july.refresh_from_db()
        assert june.max_1h == 130.0
        assert july.max_1h == 130.0
        assert 'o3: 2 rows changed' in out

    def test_end_on_month_boundary_leaves_next_month(self):
        june = self.o3_day(day=pacific_day(2026, 6, 30))
        july = self.o3_day(day=pacific_day(2026, 7, 1))
        self.run_command('2026-06-01', '2026-07-01', '--monitor', str(self.monitor.pk))
        june.refresh_from_db()
        july.refresh_from_db()
        assert june.max_1h == 130.0
        assert july.max_1h is None

    def test_command_prints_skips(self):
        self.hourly(self.monitor, 'o3', [-999.0] + [10.0] * 23, self.hours)
        self.daily(self.monitor, 'o3', self.day)
        out = self.run_command('2026-07-01', '2026-07-02', '--monitor', str(self.monitor.pk))
        assert 'skipped 1 hourly value(s) at or below -900' in out

    def test_start_mid_month_leaves_earlier_rows(self):
        early = self.o3_day(day=pacific_day(2026, 7, 1))
        late = self.o3_day(day=pacific_day(2026, 7, 2))
        self.run_command('2026-07-02', '2026-07-03', '--monitor', str(self.monitor.pk))
        early.refresh_from_db()
        late.refresh_from_db()
        assert early.max_1h is None
        assert late.max_1h == 130.0

    def test_chunk_bounds(self):
        with patch('camp.apps.summaries.management.commands.fill_daily_peaks.fill_daily_peaks',
                   return_value=FillResult({}, 0)) as fill:
            self.run_command('2026-01-15', '2026-03-10', '--monitor', str(self.monitor.pk))
        bounds = [(c.args[2], c.args[3]) for c in fill.call_args_list]
        assert bounds == [
            (pacific_day(2026, 1, 15), pacific_day(2026, 2, 1)),
            (pacific_day(2026, 2, 1), pacific_day(2026, 3, 1)),
            (pacific_day(2026, 3, 1), pacific_day(2026, 3, 10)),
        ]
