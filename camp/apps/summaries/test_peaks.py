from datetime import datetime, timedelta
from unittest.mock import patch

from django.conf import settings
from django.test import TestCase
from tdigest import TDigest

from camp.apps.entries import models as entries
from camp.apps.monitors.purpleair.models import PurpleAir
from camp.apps.regions.models import Region
from camp.apps.summaries.aggregators import tdigest_to_dict
from camp.apps.summaries.models import BaseSummary, MonitorSummary, RegionSummary
from camp.apps.summaries.peaks import (
    day_hours, fill_daily_peaks, max_1h, max_8h, peak_entry_models, standard_for,
)
from camp.apps.summaries.tasks import rollup_monitor_summaries, rollup_region_summaries
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
        assert raised > base

    def test_max_8h_missing_next_day(self):
        hours = day(2026, 7, 1)
        hourly = series(hours, [2.0] * 24)
        assert max_8h(hours, hourly, 9.5) == 2.0

    def test_peak_entry_models(self):
        assert peak_entry_models() == {
            entries.O3: 'max_1h',
            entries.NO2: 'max_1h',
            entries.SO2: 'max_1h',
            entries.CO: 'max_8h',
        }
        assert entries.PM25 not in peak_entry_models()

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

    def test_fills_monitor_o3(self):
        self.monitor_hours('o3', [10.0] * 23 + [130.0])
        row = self.monitor_daily('o3')
        assert self.fill() == {'o3': 1}
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
        assert self.fill('region') == {'o3': 1}
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

    def test_pm25_untouched(self):
        self.monitor_hours('pm25', [300.0] * 24)
        row = self.monitor_daily('pm25')
        assert self.fill() == {}
        row.refresh_from_db()
        assert row.max_1h is None
        assert row.max_8h is None

    def test_peaks_per_processor(self):
        self.monitor_hours('o3', [10.0] * 23 + [200.0], processor='')
        self.monitor_hours('o3', [10.0] * 23 + [90.0], processor='AQLiteHourlyAggregator')
        raw = self.monitor_daily('o3', processor='')
        cal = self.monitor_daily('o3', processor='AQLiteHourlyAggregator')
        assert self.fill() == {'o3': 2}
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
        assert self.fill(dry_run=True) == {'o3': 1}
        row.refresh_from_db()
        assert row.max_1h is None

    def test_entry_models_subset_and_progress(self):
        self.monitor_hours('o3', [10.0] * 24)
        self.monitor_hours('co', [2.0] * 24)
        o3 = self.monitor_daily('o3')
        co = self.monitor_daily('co')
        messages = []
        result = self.fill(entry_models=[entries.CO], progress=messages.append)
        assert result == {'co': 1}
        o3.refresh_from_db()
        co.refresh_from_db()
        assert o3.max_1h is None
        assert co.max_8h == 2.0
        assert len(messages) == 1

    def test_unchanged_rows_not_counted(self):
        self.monitor_hours('o3', [10.0] * 24)
        self.monitor_daily('o3')
        assert self.fill() == {'o3': 1}
        assert self.fill() == {}

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
        with patch('camp.apps.summaries.tasks.fill_daily_peaks') as fill:
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
        with patch('camp.apps.summaries.tasks.fill_daily_peaks'):
            rollup_region_summaries(R.DAILY, R.HOURLY, self.day, self.next_day)
        region_daily = RegionSummary.objects.get(resolution=R.DAILY, entry_type='o3')
        assert region_daily.max_1h == 130.0
