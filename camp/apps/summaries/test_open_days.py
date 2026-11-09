from datetime import datetime, timedelta

from django.conf import settings
from django.db import connection
from django.db.models import Q
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from tdigest import TDigest

from camp.apps.entries import models as entries
from camp.apps.monitors.purpleair.models import PurpleAir
from camp.apps.regions.models import Region
from camp.apps.summaries.aggregators import tdigest_to_dict
from camp.apps.summaries.models import BaseSummary, MonitorSummary, RegionSummary
from camp.apps.summaries.open_days import build_open_rows, open_days
from camp.apps.summaries.peaks import SO_FAR_FUNCTIONS, day_hours
from camp.utils.datetime import make_aware

R = BaseSummary.Resolution


def pacific(y, m, d, hour=0, minute=0):
    return make_aware(datetime(y, m, d, hour, minute), settings.DEFAULT_TIMEZONE)


def _stats(mean):
    digest = TDigest()
    digest.update(mean)
    return dict(
        count=1, expected_count=1, sum_value=mean, sum_of_squares=mean * mean,
        tdigest=tdigest_to_dict(digest), minimum=mean, maximum=mean, mean=mean,
        stddev=0.0, p25=mean, p75=mean,
    )


class OpenDaysWindowTests(TestCase):
    def test_open_days_window(self):
        assert open_days(pacific(2026, 7, 2, 0, 30)) == [pacific(2026, 7, 1), pacific(2026, 7, 2)]
        assert open_days(pacific(2026, 7, 2, 2, 59)) == [pacific(2026, 7, 1), pacific(2026, 7, 2)]
        assert open_days(pacific(2026, 7, 2, 3, 0)) == [pacific(2026, 7, 2)]
        assert open_days(pacific(2026, 7, 2, 23, 59)) == [pacific(2026, 7, 2)]

    def test_open_days_dst(self):
        # Fall back: 2026-11-01 has 25 hours and ends at 00:00 PST on 11-02.
        days = open_days(pacific(2026, 11, 2, 2, 30))
        assert days == [pacific(2026, 11, 1), pacific(2026, 11, 2)]
        assert len(day_hours(days[0])) == 25
        assert open_days(pacific(2026, 11, 2, 3, 0)) == [pacific(2026, 11, 2)]

        # Spring forward: 2026-03-08 has 23 hours.
        days = open_days(pacific(2026, 3, 9, 2, 30))
        assert days == [pacific(2026, 3, 8), pacific(2026, 3, 9)]
        assert len(day_hours(days[0])) == 23
        assert len(day_hours(days[1])) == 24


class SoFarFunctionTests(TestCase):
    def setUp(self):
        self.hours = day_hours(pacific(2026, 7, 2))

    def series(self, values, start=0):
        return {self.hours[start + i]: v for i, v in enumerate(values)}

    def test_no_data(self):
        for fn in SO_FAR_FUNCTIONS.values():
            assert fn(self.hours, {}) is None

    def test_max_8h_only_windows_starting_today(self):
        # Hours from the previous day don't make a window that starts today.
        before = {self.hours[0] - timedelta(hours=k): 50.0 for k in range(1, 8)}
        series = {**before, **self.series([10.0] * 5)}
        assert SO_FAR_FUNCTIONS['max_8h'](self.hours, series) is None
        series = {**before, **self.series([10.0] * 6)}
        assert SO_FAR_FUNCTIONS['max_8h'](self.hours, series) == 10.0


class BuildOpenRowsTests(TestCase):
    fixtures = ['purple-air.yaml', 'regions.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.first()
        self.region = Region.objects.filter(boundary__isnull=False).first()
        self.yesterday = pacific(2026, 7, 1)
        self.today = pacific(2026, 7, 2)
        self.midday = pacific(2026, 7, 2, 12)
        self.after_midnight = pacific(2026, 7, 2, 0, 30)

    def monitor_hours(self, entry_type, values, day=None, processor='', is_complete=True,
                      start=0, monitor=None):
        hours = day_hours(day or self.today)
        for i, v in enumerate(values):
            MonitorSummary.objects.create(
                monitor=monitor or self.monitor, timestamp=hours[start + i], resolution=R.HOURLY,
                entry_type=entry_type, processor=processor, is_complete=is_complete, **_stats(v),
            )

    def monitor_daily(self, entry_type, day, processor=''):
        return MonitorSummary.objects.create(
            monitor=self.monitor, timestamp=day, resolution=R.DAILY,
            entry_type=entry_type, processor=processor, is_complete=True, **_stats(1.0),
        )

    def region_hours(self, entry_type, values, station_counts=None, day=None):
        hours = day_hours(day or self.today)
        for i, v in enumerate(values):
            RegionSummary.objects.create(
                region=self.region, timestamp=hours[i], resolution=R.HOURLY,
                entry_type=entry_type, weight=1.0,
                station_count=station_counts[i] if station_counts else 1, **_stats(v),
            )

    def rows(self, entry_model, now=None, kind='monitor', **kwargs):
        owner = self.monitor.pk if kind == 'monitor' else self.region.pk
        result = build_open_rows(kind, [owner], entry_model, now or self.midday, **kwargs)
        return result.get(owner, [])

    def test_today_so_far_figures(self):
        self.monitor_hours('o3', [40.0, 90.0, 60.0])
        [row] = self.rows(entries.O3)
        assert isinstance(row, MonitorSummary)
        assert row.pk is not None and row._state.adding  # unsaved
        assert row.resolution == R.DAILY
        assert row.timestamp == self.today
        assert row.max_1h == 90.0
        assert row.max_8h is None and row.mean_24h is None
        assert row.count == 3
        assert row.mean == 190.0 / 3
        assert row.minimum == 40.0 and row.maximum == 90.0

        self.monitor_hours('pm25', [10.0, 20.0])
        [row] = self.rows(entries.PM25)
        assert row.mean_24h == 15.0
        assert row.max_1h is None and row.max_8h is None

        self.monitor_hours('co', [1.0, 2.0, 3.0, 4.0, 5.0])
        [row] = self.rows(entries.CO)
        assert row.max_8h is None
        self.monitor_hours('co', [6.0], start=5)
        [row] = self.rows(entries.CO)
        assert row.max_8h == 3.5
        assert row.max_1h is None and row.mean_24h is None

    def test_today_incomplete_hours(self):
        self.monitor_hours('o3', [40.0, 90.0], is_complete=False)
        [row] = self.rows(entries.O3)
        assert row.count == 2
        assert row.mean == 65.0
        assert row.max_1h is None

    def test_sentinel_skipped_so_far(self):
        self.monitor_hours('o3', [-999.0, 40.0])
        [row] = self.rows(entries.O3)
        assert row.max_1h == 40.0

        self.monitor_hours('pm25', [-999.0, 10.0, 20.0])
        [row] = self.rows(entries.PM25)
        assert row.mean_24h == 15.0

    def test_yesterday_strict(self):
        self.monitor_hours('o3', [50.0] * 17, day=self.yesterday)
        rows = self.rows(entries.O3, now=self.after_midnight)
        assert [r.timestamp for r in rows] == [self.yesterday]
        assert rows[0].count == 17
        assert rows[0].max_1h is None

        # 18 of 24 meets the 75% rule.
        self.monitor_hours('o3', [50.0], day=self.yesterday, start=17)
        [row] = self.rows(entries.O3, now=self.after_midnight)
        assert row.max_1h == 50.0

    def test_yesterday_max_8h_uses_tail(self):
        # Yesterday's last window (23:00) reaches into today's first hours.
        hours = day_hours(self.yesterday)
        for h in hours:
            MonitorSummary.objects.create(
                monitor=self.monitor, timestamp=h, resolution=R.HOURLY, entry_type='co',
                processor='', is_complete=True, **_stats(1.0),
            )
        self.monitor_hours('co', [100.0] * 7)
        rows = self.rows(entries.CO, now=pacific(2026, 7, 2, 2))
        by_day = {r.timestamp: r for r in rows}
        # Stats use only the day's own hours.
        assert by_day[self.yesterday].count == 24
        assert by_day[self.yesterday].maximum == 1.0
        # Window at 23:00: 1 + 7 x 100 over 8 hours.
        assert by_day[self.yesterday].max_8h == (1.0 + 700.0) / 8
        assert by_day[self.today].count == 7

    def test_stored_yesterday_not_open(self):
        self.monitor_hours('o3', [50.0] * 24, day=self.yesterday)
        self.monitor_hours('o3', [40.0])
        self.monitor_hours('o3', [50.0] * 24, day=self.yesterday, processor='Other')
        self.monitor_hours('o3', [40.0], processor='Other')

        rows = self.rows(entries.O3, now=self.after_midnight)
        assert len(rows) == 4

        self.monitor_daily('o3', self.yesterday)
        rows = self.rows(entries.O3, now=self.after_midnight)
        got = sorted((r.processor, r.timestamp) for r in rows)
        assert got == [
            ('', self.today),
            ('Other', self.yesterday),
            ('Other', self.today),
        ]

    def test_region_rows(self):
        self.region_hours('pm25', [10.0, 20.0, 30.0], station_counts=[1, 3, 2])
        [row] = self.rows(entries.PM25, kind='region')
        assert isinstance(row, RegionSummary)
        assert row.region_id == self.region.pk
        assert row.timestamp == self.today and row.resolution == R.DAILY
        assert row.station_count == 3
        assert row.weight == 3.0
        assert row.mean == 20.0
        assert row.mean_24h == 20.0
        assert not hasattr(row, 'is_complete')

    def test_region_stored_yesterday_not_open(self):
        self.region_hours('pm25', [10.0], day=self.yesterday)
        self.region_hours('pm25', [20.0])
        assert len(self.rows(entries.PM25, kind='region', now=self.after_midnight)) == 2
        RegionSummary.objects.create(
            region=self.region, timestamp=self.yesterday, resolution=R.DAILY,
            entry_type='pm25', station_count=1, weight=1.0, **_stats(1.0),
        )
        [row] = self.rows(entries.PM25, kind='region', now=self.after_midnight)
        assert row.timestamp == self.today

    def test_processor_q(self):
        for day in (self.yesterday, self.today):
            self.monitor_hours('o3', [40.0], day=day)
            self.monitor_hours('o3', [50.0], day=day, processor='AQLiteHourlyAggregator')

        rows = self.rows(entries.O3, now=self.after_midnight)
        assert sorted((r.processor, r.timestamp) for r in rows) == [
            ('', self.yesterday), ('', self.today),
            ('AQLiteHourlyAggregator', self.yesterday), ('AQLiteHourlyAggregator', self.today),
        ]

        rows = self.rows(
            entries.O3, now=self.after_midnight, processor_q=Q(processor='AQLiteHourlyAggregator'),
        )
        assert sorted((r.processor, r.timestamp) for r in rows) == [
            ('AQLiteHourlyAggregator', self.yesterday), ('AQLiteHourlyAggregator', self.today),
        ]

    def test_other_entry_types_ignored(self):
        self.monitor_hours('pm25', [10.0])
        assert self.rows(entries.O3) == []

    def test_no_hourly_rows_no_open_row(self):
        assert self.rows(entries.O3, now=self.after_midnight) == []
        assert build_open_rows('monitor', [self.monitor.pk], entries.O3, self.midday) == {}

    def test_no_figure_type(self):
        self.monitor_hours('temperature', [70.0, 80.0])
        [row] = self.rows(entries.Temperature)
        assert row.count == 2
        assert row.max_1h is None and row.max_8h is None and row.mean_24h is None

    def test_unknown_kind(self):
        with self.assertRaises(ValueError):
            build_open_rows('station', [], entries.O3, self.midday)

    def test_query_count(self):
        monitors = [self.monitor] + [
            PurpleAir.objects.create(name=f'M{i}', position='POINT(0 0)', sensor_id=90000 + i)
            for i in range(4)
        ]
        for m in monitors:
            self.monitor_hours('o3', [40.0] * 3, day=self.yesterday, monitor=m)
            self.monitor_hours('o3', [40.0] * 3, monitor=m)
        ids = [m.pk for m in monitors]

        with CaptureQueriesContext(connection) as ctx:
            result = build_open_rows('monitor', ids, entries.O3, self.after_midnight)
        assert len(ctx.captured_queries) <= 2
        assert sum(len(v) for v in result.values()) == 10
        assert set(result) == set(ids)

        # Without an open yesterday, the existence check isn't needed.
        with CaptureQueriesContext(connection) as ctx:
            build_open_rows('monitor', ids, entries.O3, self.midday)
        assert len(ctx.captured_queries) == 1
