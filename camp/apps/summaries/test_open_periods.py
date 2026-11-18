from contextlib import contextmanager
from datetime import datetime
from unittest import mock

from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.db.models import Q
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from tdigest import TDigest

from camp.api.v2.summaries.serializers import (
    MonitorSummarySerializer, RegionSummarySerializer, serializing_at,
)
from camp.apps.entries import models as entries
from camp.apps.monitors.purpleair.models import PurpleAir
from camp.apps.regions.models import Region
from camp.apps.summaries import open_periods as open_periods_module
from camp.apps.summaries.aggregators import rollup_region_stats, rollup_summaries, tdigest_to_dict
from camp.apps.summaries.models import BaseSummary, MonitorSummary, RegionSummary
from camp.apps.summaries.open_days import STATS_COLUMNS, build_open_rows
from camp.apps.summaries.open_periods import (
    build_open_period_rows, cached_open_period_rows, open_periods,
)
from camp.apps.summaries.peaks import day_hours
from camp.apps.summaries.periods import iter_period_starts
from camp.utils.datetime import make_aware

R = BaseSummary.Resolution


def pacific(y, m, d, hour=0, minute=0):
    return make_aware(datetime(y, m, d, hour, minute), settings.DEFAULT_TIMEZONE)


def _stats(mean, count=1):
    digest = TDigest()
    digest.update(mean, count)
    return dict(
        count=count, expected_count=count, sum_value=mean * count,
        sum_of_squares=mean * mean * count, tdigest=tdigest_to_dict(digest),
        minimum=mean, maximum=mean, mean=mean, stddev=0.0, p25=mean, p75=mean,
    )


def days_between(start, end):
    return list(iter_period_starts('day', start, end))


class OpenPeriodsWindowTests(TestCase):
    def test_month(self):
        assert open_periods('month', pacific(2026, 12, 1, 0, 30)) == [pacific(2026, 11, 1), pacific(2026, 12, 1)]
        assert open_periods('month', pacific(2026, 12, 1, 3, 59)) == [pacific(2026, 11, 1), pacific(2026, 12, 1)]
        assert open_periods('month', pacific(2026, 12, 1, 4, 0)) == [pacific(2026, 12, 1)]
        assert open_periods('month', pacific(2026, 11, 17, 12)) == [pacific(2026, 11, 1)]

    def test_year(self):
        assert open_periods('year', pacific(2027, 1, 1, 0, 30)) == [pacific(2026, 1, 1), pacific(2027, 1, 1)]
        assert open_periods('year', pacific(2027, 1, 1, 5, 0)) == [pacific(2027, 1, 1)]

    def test_quarter_and_season(self):
        now = pacific(2026, 12, 1, 0, 30)
        assert open_periods('season', now) == [pacific(2026, 9, 1), pacific(2026, 12, 1)]
        # Q4 hasn't ended, so only it is open.
        assert open_periods('quarter', now) == [pacific(2026, 10, 1)]


class OpenPeriodRowsMixin:
    fixtures = ['purple-air.yaml', 'regions.yaml']

    def setUp(self):
        cache.clear()
        self.monitor = PurpleAir.objects.first()
        self.region = Region.objects.filter(boundary__isnull=False).first()
        self.today = pacific(2026, 11, 17)
        self.midday = pacific(2026, 11, 17, 12)

    def owner_kwargs(self, kind, processor='', weight=1.0):
        if kind == 'monitor':
            return dict(monitor=self.monitor, processor=processor, is_complete=True)
        return dict(region=self.region, weight=weight, station_count=2)

    def model(self, kind):
        return MonitorSummary if kind == 'monitor' else RegionSummary

    def daily(self, kind, entry_type, day, mean, figure=None, field='max_1h', **kwargs):
        extra = {field: figure} if figure is not None else {}
        return self.model(kind).objects.create(
            timestamp=day, resolution=R.DAILY, entry_type=entry_type,
            **self.owner_kwargs(kind, weight=24.0, **kwargs), **_stats(mean, count=24), **extra,
        )

    def hours(self, kind, entry_type, day, values, **kwargs):
        hours = day_hours(day)
        return [
            self.model(kind).objects.create(
                timestamp=hours[i], resolution=R.HOURLY, entry_type=entry_type,
                **self.owner_kwargs(kind, **kwargs), **_stats(v),
            )
            for i, v in enumerate(values)
        ]

    def monthly(self, kind, entry_type, month, mean, **kwargs):
        return self.model(kind).objects.create(
            timestamp=month, resolution=R.MONTHLY, entry_type=entry_type,
            **self.owner_kwargs(kind, weight=500.0, **kwargs), **_stats(mean, count=500),
        )

    def owner(self, kind):
        return self.monitor.pk if kind == 'monitor' else self.region.pk

    def rows(self, kind, entry_model, resolution, now=None, **kwargs):
        result = build_open_period_rows(
            kind, [self.owner(kind)], entry_model, resolution, now or self.midday, **kwargs,
        )
        return result.get(self.owner(kind), [])

    def values(self, objs):
        model = type(objs[0])
        extra = ('weight',) if model is RegionSummary else ()
        return list(
            model.objects.filter(pk__in=[o.pk for o in objs])
            .order_by('timestamp', 'resolution').values(*STATS_COLUMNS, *extra)
        )

    def rollup(self, kind, objs):
        fn = rollup_summaries if kind == 'monitor' else rollup_region_stats
        return fn(self.values(objs), with_tdigest=False)

    def assert_stats(self, row, expected):
        for field in ('count', 'expected_count', 'sum_value', 'sum_of_squares', 'minimum', 'maximum'):
            assert getattr(row, field) == expected[field], field
        assert abs(row.mean - expected['mean']) < 1e-9
        assert abs(row.stddev - expected['stddev']) < 1e-9


class BuildOpenPeriodRowsTests(OpenPeriodRowsMixin, TestCase):
    def check_current_month(self, kind):
        nov = days_between(pacific(2026, 11, 1), self.today)
        assert len(nov) == 16
        dailies = [self.daily(kind, 'o3', d, 40.0 + i, figure=50.0 + i) for i, d in enumerate(nov)]
        hourlies = self.hours(kind, 'o3', self.today, [40.0, 90.0, 60.0])

        [row] = self.rows(kind, entries.O3, 'month')
        assert isinstance(row, self.model(kind))
        assert row._state.adding
        assert row.resolution == R.MONTHLY
        assert row.timestamp == pacific(2026, 11, 1)
        assert row.entry_type == 'o3'
        assert row.daily_statistic_expected_days == 17
        assert row.daily_statistic_days == 17
        figures = [50.0 + i for i in range(16)] + [90.0]
        assert abs(row.daily_statistic_mean - sum(figures) / 17) < 1e-9
        self.assert_stats(row, self.rollup(kind, dailies + hourlies))
        assert row.max_1h is None and row.max_8h is None and row.mean_24h is None
        assert row.tdigest is None

        serializer = MonitorSummarySerializer if kind == 'monitor' else RegionSummarySerializer
        with serializing_at(self.midday):
            [data] = serializer([row]).serialize()
        assert data['is_final'] is False
        assert data['daily_statistic_expected_days'] == 17
        return row

    def test_current_month_monitor(self):
        row = self.check_current_month('monitor')
        assert row.monitor_id == self.monitor.pk and row.processor == ''
        assert row.is_complete is True

    def test_current_month_region(self):
        row = self.check_current_month('region')
        assert row.region_id == self.region.pk
        assert row.station_count == 2
        assert row.weight == 16 * 24 + 3

    def test_yesterday_unstored(self):
        now = pacific(2026, 11, 17, 1, 0)
        for d in days_between(pacific(2026, 11, 1), pacific(2026, 11, 16)):
            self.daily('monitor', 'o3', d, 40.0, figure=50.0)
        # Nov 16 isn't stored yet: its strict figure (18 of 24 hours) is used.
        self.hours('monitor', 'o3', pacific(2026, 11, 16), [70.0] * 18)
        self.hours('monitor', 'o3', self.today, [30.0])

        [row] = self.rows('monitor', entries.O3, 'month', now=now)
        assert row.daily_statistic_expected_days == 17
        assert row.daily_statistic_days == 17
        assert abs(row.daily_statistic_mean - (15 * 50.0 + 70.0 + 30.0) / 17) < 1e-9
        assert row.count == 15 * 24 + 18 + 1

        # With fewer than 18 hours yesterday's strict figure is null.
        MonitorSummary.objects.filter(
            resolution=R.HOURLY, timestamp=day_hours(pacific(2026, 11, 16))[17],
        ).delete()
        [row] = self.rows('monitor', entries.O3, 'month', now=now)
        assert row.daily_statistic_days == 16
        assert row.count == 15 * 24 + 17 + 1

    def test_stored_today_daily_used_once(self):
        # A stored daily row wins over the open-day row for the same day.
        self.daily('monitor', 'o3', self.today, 40.0, figure=55.0)
        self.hours('monitor', 'o3', self.today, [90.0])
        [row] = self.rows('monitor', entries.O3, 'month')
        assert row.count == 24
        assert row.daily_statistic_days == 1

    def test_previous_month_while_open(self):
        now = pacific(2026, 12, 1, 0, 30)
        for d in days_between(pacific(2026, 11, 1), pacific(2026, 11, 30)):
            self.daily('monitor', 'o3', d, 40.0, figure=50.0)
        self.hours('monitor', 'o3', pacific(2026, 11, 30), [60.0] * 24)
        self.hours('monitor', 'o3', pacific(2026, 12, 1), [20.0])

        rows = self.rows('monitor', entries.O3, 'month', now=now)
        assert [r.timestamp for r in rows] == [pacific(2026, 11, 1), pacific(2026, 12, 1)]
        nov, dec = rows
        assert nov.daily_statistic_expected_days == 30
        assert nov.daily_statistic_days == 30
        assert abs(nov.daily_statistic_mean - (29 * 50.0 + 60.0) / 30) < 1e-9
        assert nov.count == 29 * 24 + 24
        assert dec.daily_statistic_expected_days == 1
        assert dec.daily_statistic_days == 1
        assert dec.daily_statistic_mean == 20.0
        assert dec.count == 1

        # Once November's monthly row is stored, only December is open.
        self.monthly('monitor', 'o3', pacific(2026, 11, 1), 40.0)
        rows = self.rows('monitor', entries.O3, 'month', now=now)
        assert [r.timestamp for r in rows] == [pacific(2026, 12, 1)]

    def test_previous_month_drops_out_when_settled(self):
        for d in days_between(pacific(2026, 11, 1), pacific(2026, 12, 1)):
            self.daily('monitor', 'o3', d, 40.0, figure=50.0)
        self.hours('monitor', 'o3', pacific(2026, 12, 1), [20.0])
        rows = self.rows('monitor', entries.O3, 'month', now=pacific(2026, 12, 1, 4, 0))
        assert [r.timestamp for r in rows] == [pacific(2026, 12, 1)]

    def test_previous_year_at_new_year(self):
        # Never more than two rows per series; the previous year's stored months stand in.
        now = pacific(2027, 1, 1, 0, 30)
        for m in range(1, 12):
            self.monthly('monitor', 'o3', pacific(2026, m, 1), 40.0)
        for d in days_between(pacific(2026, 1, 1), pacific(2026, 12, 31)):
            self.daily('monitor', 'o3', d, 40.0, figure=50.0)
        self.hours('monitor', 'o3', pacific(2026, 12, 31), [60.0] * 24)
        self.hours('monitor', 'o3', pacific(2027, 1, 1), [20.0])

        rows = self.rows('monitor', entries.O3, 'year', now=now)
        assert [r.timestamp for r in rows] == [pacific(2026, 1, 1), pacific(2027, 1, 1)]
        prev, cur = rows
        assert prev.daily_statistic_expected_days == 365
        assert prev.daily_statistic_days == 365
        assert prev.count == 11 * 500 + 30 * 24 + 24
        assert cur.daily_statistic_expected_days == 1
        assert cur.count == 1

        # The stored 2026 yearly row closes it.
        self.model('monitor').objects.create(
            timestamp=pacific(2026, 1, 1), resolution=R.YEARLY, entry_type='o3',
            **self.owner_kwargs('monitor'), **_stats(40.0, count=8000),
        )
        rows = self.rows('monitor', entries.O3, 'year', now=now)
        assert [r.timestamp for r in rows] == [pacific(2027, 1, 1)]

    def check_quarter_uses_stored_months(self, kind):
        october = self.monthly(kind, 'o3', pacific(2026, 10, 1), 33.0)
        # October's daily rows give the figures but not the stats (the monthly row stands in).
        for d in days_between(pacific(2026, 10, 1), pacific(2026, 11, 1)):
            self.daily(kind, 'o3', d, 99.0, figure=60.0)
        nov = [
            self.daily(kind, 'o3', d, 40.0, figure=50.0)
            for d in days_between(pacific(2026, 11, 1), self.today)
        ]
        hourlies = self.hours(kind, 'o3', self.today, [40.0, 70.0])

        [row] = self.rows(kind, entries.O3, 'quarter')
        assert row.resolution == R.QUARTERLY
        assert row.timestamp == pacific(2026, 10, 1)
        self.assert_stats(row, self.rollup(kind, [october, *nov, *hourlies]))
        assert row.daily_statistic_expected_days == 48
        assert row.daily_statistic_days == 48
        assert abs(row.daily_statistic_mean - (31 * 60.0 + 16 * 50.0 + 70.0) / 48) < 1e-9

    def test_quarter_uses_stored_months_monitor(self):
        self.check_quarter_uses_stored_months('monitor')

    def test_quarter_uses_stored_months_region(self):
        self.check_quarter_uses_stored_months('region')

    def test_threshold(self):
        for i, d in enumerate(days_between(pacific(2026, 11, 1), self.today)):
            self.daily('monitor', 'o3', d, 40.0, figure=50.0 if i < 10 else None)
        [row] = self.rows('monitor', entries.O3, 'month')
        assert row.daily_statistic_mean is None
        assert row.daily_statistic_days == 10
        assert row.daily_statistic_expected_days == 17

        # 13 of 17 meets the 75% rule.
        for d in days_between(pacific(2026, 11, 11), pacific(2026, 11, 14)):
            MonitorSummary.objects.filter(resolution=R.DAILY, timestamp=d).update(max_1h=50.0)
        [row] = self.rows('monitor', entries.O3, 'month')
        assert row.daily_statistic_days == 13
        assert row.daily_statistic_mean == 50.0

    def test_mean_24h_and_max_8h_types(self):
        for d in days_between(pacific(2026, 11, 1), self.today):
            self.daily('monitor', 'pm25', d, 10.0, figure=12.0, field='mean_24h')
            self.daily('monitor', 'co', d, 1.0, figure=2.0, field='max_8h')
        [pm] = self.rows('monitor', entries.PM25, 'month')
        assert pm.daily_statistic_days == 16 and pm.daily_statistic_mean == 12.0
        assert pm.mean_24h is None
        [co] = self.rows('monitor', entries.CO, 'month')
        assert co.daily_statistic_days == 16 and co.daily_statistic_mean == 2.0
        assert co.max_8h is None

    def test_non_peak_type(self):
        dailies = [
            self.daily('monitor', 'temperature', d, 70.0)
            for d in days_between(pacific(2026, 11, 1), self.today)
        ]
        hourlies = self.hours('monitor', 'temperature', self.today, [60.0, 80.0])
        [row] = self.rows('monitor', entries.Temperature, 'month')
        self.assert_stats(row, self.rollup('monitor', dailies + hourlies))
        assert row.daily_statistic_mean is None
        assert row.daily_statistic_days is None
        assert row.daily_statistic_expected_days is None
        assert row.max_1h is None and row.max_8h is None and row.mean_24h is None

    def test_processors_are_separate_series(self):
        for d in days_between(pacific(2026, 11, 1), self.today):
            self.daily('monitor', 'o3', d, 40.0, figure=50.0)
            self.daily('monitor', 'o3', d, 40.0, figure=80.0, processor='Other')
        rows = self.rows('monitor', entries.O3, 'month')
        by_processor = {r.processor: r for r in rows}
        assert set(by_processor) == {'', 'Other'}
        assert by_processor[''].daily_statistic_mean == 50.0
        assert by_processor['Other'].daily_statistic_mean == 80.0

        [row] = self.rows('monitor', entries.O3, 'month', processor_q=Q(processor='Other'))
        assert row.processor == 'Other'

    def test_no_rows(self):
        other = PurpleAir.objects.create(name='Empty', position='POINT(0 0)', sensor_id=92000)
        self.daily('monitor', 'o3', pacific(2026, 11, 3), 40.0, figure=50.0)
        # Rows outside the open period don't count.
        self.daily('monitor', 'o3', pacific(2026, 10, 3), 40.0, figure=50.0, processor='Old')
        result = build_open_period_rows(
            'monitor', [self.monitor.pk, other.pk], entries.O3, 'month', self.midday,
        )
        assert set(result) == {self.monitor.pk}
        assert [r.processor for r in result[self.monitor.pk]] == ['']
        assert build_open_period_rows('monitor', [other.pk], entries.O3, 'month', self.midday) == {}

    def test_unknown_kind(self):
        with self.assertRaises(ValueError):
            build_open_period_rows('station', [], entries.O3, 'month', self.midday)

    def test_query_count(self):
        monitors = [self.monitor] + [
            PurpleAir.objects.create(name=f'M{i}', position='POINT(0 0)', sensor_id=93000 + i)
            for i in range(3)
        ]
        for m in monitors:
            MonitorSummary.objects.create(
                monitor=m, timestamp=pacific(2026, 10, 1), resolution=R.MONTHLY,
                entry_type='o3', processor='', is_complete=True, **_stats(40.0),
            )
            for d in days_between(pacific(2026, 11, 1), pacific(2026, 11, 4)):
                MonitorSummary.objects.create(
                    monitor=m, timestamp=d, resolution=R.DAILY, entry_type='o3',
                    processor='', is_complete=True, max_1h=50.0, **_stats(40.0),
                )
        ids = [m.pk for m in monitors]
        # The coarse read, the daily stats read (October's days left out), the daily
        # figure read and the open days' hourly read.
        with CaptureQueriesContext(connection) as ctx:
            result = build_open_period_rows('monitor', ids, entries.O3, 'quarter', self.midday)
        assert len(ctx.captured_queries) == 4
        assert set(result) == set(ids)
        assert all(r.count == 1 + 3 for rows in result.values() for r in rows)
        # Plus build_open_rows' stored-yesterday check when yesterday is open.
        self.hours('monitor', 'o3', pacific(2026, 12, 31), [40.0])
        with CaptureQueriesContext(connection) as ctx:
            build_open_period_rows('monitor', ids, entries.O3, 'year', pacific(2027, 1, 1, 0, 30))
        assert len(ctx.captured_queries) == 5
        # A month has no stand-ins: one daily read carries stats and figures.
        with CaptureQueriesContext(connection) as ctx:
            build_open_period_rows('monitor', ids, entries.O3, 'month', self.midday)
        assert len(ctx.captured_queries) == 3

    def test_covered_days_not_fetched_for_stats(self):
        self.monthly('monitor', 'o3', pacific(2026, 10, 1), 33.0)
        self.daily('monitor', 'o3', pacific(2026, 10, 5), 99.0, figure=60.0)
        self.daily('monitor', 'o3', pacific(2026, 11, 5), 40.0, figure=50.0)
        with CaptureQueriesContext(connection) as ctx:
            self.rows('monitor', entries.O3, 'quarter')
        stats_reads = [q['sql'] for q in ctx.captured_queries if '"tdigest"' in q['sql'] and "'day'" in q['sql']]
        assert len(stats_reads) == 1
        assert 'NOT' in stats_reads[0]

    @contextmanager
    def exclusion_terms(self):
        terms = []
        real = open_periods_module._exclusions

        def spy(*args):
            terms.extend(real(*args))
            return terms

        with mock.patch.object(open_periods_module, '_exclusions', side_effect=spy):
            yield terms

    def test_exclusion_terms_shared(self):
        # Ten monitors with the same stored months share one exclusion term per
        # processor set; a processor stored for every monitor joins it.
        monitors = [self.monitor] + [
            PurpleAir.objects.create(name=f'X{i}', position='POINT(0 0)', sensor_id=94000 + i)
            for i in range(9)
        ]
        for m in monitors:
            for processor in ('', 'Other'):
                for month in (1, 2, 3):
                    MonitorSummary.objects.create(
                        monitor=m, timestamp=pacific(2026, month, 1), resolution=R.MONTHLY,
                        entry_type='o3', processor=processor, is_complete=True, **_stats(40.0),
                    )
                MonitorSummary.objects.create(
                    monitor=m, timestamp=pacific(2026, 3, 5), resolution=R.DAILY, entry_type='o3',
                    processor=processor, is_complete=True, max_1h=50.0, **_stats(99.0),
                )
                MonitorSummary.objects.create(
                    monitor=m, timestamp=pacific(2026, 4, 5), resolution=R.DAILY, entry_type='o3',
                    processor=processor, is_complete=True, max_1h=50.0, **_stats(20.0),
                )
        ids = [m.pk for m in monitors]

        with self.exclusion_terms() as terms:
            result = build_open_period_rows('monitor', ids, entries.O3, 'year', self.midday)
        assert len(terms) == 1
        for rows in result.values():
            for row in rows:
                # Three monthly rows plus April's daily row; March's daily is left out.
                assert row.count == 4
                assert row.daily_statistic_days == 2

        # One monitor without an 'Other' March: its runs differ, so a second term.
        MonitorSummary.objects.filter(
            monitor=monitors[0], processor='Other', resolution=R.MONTHLY, timestamp=pacific(2026, 3, 1),
        ).delete()
        with self.exclusion_terms() as terms:
            build_open_period_rows('monitor', ids, entries.O3, 'year', self.midday)
        assert len(terms) == 3

    def test_stored_previous_period_not_read_for_stats(self):
        # The previous month is stored, so its days are left out of the stats read.
        now = pacific(2026, 12, 1, 0, 30)
        self.monthly('monitor', 'o3', pacific(2026, 11, 1), 40.0)
        self.daily('monitor', 'o3', pacific(2026, 11, 5), 40.0, figure=50.0)
        self.hours('monitor', 'o3', pacific(2026, 12, 1), [20.0])
        with CaptureQueriesContext(connection) as ctx:
            rows = self.rows('monitor', entries.O3, 'month', now=now)
        assert [r.timestamp for r in rows] == [pacific(2026, 12, 1)]
        stats_reads = [q['sql'] for q in ctx.captured_queries if '"tdigest"' in q['sql'] and "'day'" in q['sql']]
        assert len(stats_reads) == 1 and 'NOT' in stats_reads[0]

    def test_month_gaps(self):
        # Stored January, February and April stand in; March has only daily rows.
        stored = [self.monthly('monitor', 'o3', pacific(2026, m, 1), 30.0 + m) for m in (1, 2, 4)]
        march = [self.daily('monitor', 'o3', pacific(2026, 3, d), 20.0, figure=50.0) for d in (1, 2)]
        self.daily('monitor', 'o3', pacific(2026, 4, 1), 99.0, figure=50.0)
        [row] = self.rows('monitor', entries.O3, 'year')
        self.assert_stats(row, self.rollup('monitor', stored + march))
        assert row.daily_statistic_days == 3

    def test_open_yesterday_in_covered_month(self):
        # 01:30 on Dec 1: November's monthly row is stored but Nov 30 is still an
        # open day with no stored daily row. Its stats are in the monthly row; its
        # figure still counts.
        now = pacific(2026, 12, 1, 1, 30)
        november = self.monthly('monitor', 'o3', pacific(2026, 11, 1), 40.0)
        self.daily('monitor', 'o3', pacific(2026, 11, 5), 40.0, figure=50.0)
        self.hours('monitor', 'o3', pacific(2026, 11, 30), [70.0] * 24)
        today = self.hours('monitor', 'o3', pacific(2026, 12, 1), [20.0])
        [row] = self.rows('monitor', entries.O3, 'quarter', now=now)
        self.assert_stats(row, self.rollup('monitor', [november, *today]))
        assert row.daily_statistic_days == 3
        assert row.daily_statistic_expected_days == 62

    def check_new_year_season(self, kind):
        now = pacific(2027, 1, 15, 12)
        december = self.monthly(kind, 'o3', pacific(2026, 12, 1), 33.0)
        for d in days_between(pacific(2026, 12, 1), pacific(2027, 1, 1)):
            self.daily(kind, 'o3', d, 99.0, figure=60.0)
        january = [
            self.daily(kind, 'o3', d, 40.0, figure=50.0)
            for d in days_between(pacific(2027, 1, 1), pacific(2027, 1, 15))
        ]
        today = self.hours(kind, 'o3', pacific(2027, 1, 15), [40.0, 70.0])

        [season] = self.rows(kind, entries.O3, 'season', now=now)
        assert season.timestamp == pacific(2026, 12, 1)
        self.assert_stats(season, self.rollup(kind, [december, *january, *today]))
        assert season.daily_statistic_expected_days == 46
        assert season.daily_statistic_days == 46
        assert abs(season.daily_statistic_mean - (31 * 60.0 + 14 * 50.0 + 70.0) / 46) < 1e-9

        [year] = self.rows(kind, entries.O3, 'year', now=now)
        assert year.timestamp == pacific(2027, 1, 1)
        self.assert_stats(year, self.rollup(kind, [*january, *today]))
        assert year.daily_statistic_expected_days == 15
        assert year.daily_statistic_days == 15

    def test_new_year_season_monitor(self):
        self.check_new_year_season('monitor')

    def test_new_year_season_region(self):
        self.check_new_year_season('region')

    def test_build_open_rows_with_tdigest(self):
        self.hours('monitor', 'o3', self.today, [40.0, 90.0])
        [row] = build_open_rows('monitor', [self.monitor.pk], entries.O3, self.midday,
                                with_tdigest=True)[self.monitor.pk]
        assert row.tdigest['n'] == 2
        [row] = build_open_rows('monitor', [self.monitor.pk], entries.O3, self.midday)[self.monitor.pk]
        assert row.tdigest is None


class CachedOpenPeriodRowsTests(OpenPeriodRowsMixin, TestCase):
    def setUp(self):
        super().setUp()
        for d in days_between(pacific(2026, 11, 1), self.today):
            self.daily('monitor', 'o3', d, 40.0, figure=50.0)
        self.hours('monitor', 'o3', self.today, [40.0])

    def call(self, now=None, resolution='month', **kwargs):
        return cached_open_period_rows(
            'monitor', [self.monitor.pk], entries.O3, resolution, now or self.midday, **kwargs,
        )

    def test_cached(self):
        first = self.call()
        with CaptureQueriesContext(connection) as ctx:
            again = self.call(now=pacific(2026, 11, 17, 12, 1))
        assert len(ctx.captured_queries) == 0
        [a], [b] = first[self.monitor.pk], again[self.monitor.pk]
        assert (a.timestamp, a.count, a.daily_statistic_mean) == (b.timestamp, b.count, b.daily_statistic_mean)
        assert isinstance(b, MonitorSummary) and b._state.adding

    def test_misses(self):
        self.call()
        for kwargs in (
            {'resolution': 'quarter'},
            {'processor_q': Q(processor='Other')},
            {'now': pacific(2026, 11, 18, 12)},  # another open-day set, same period
            {'now': pacific(2026, 12, 1, 0, 30)},  # another open-period set
        ):
            with CaptureQueriesContext(connection) as ctx:
                self.call(**kwargs)
            assert len(ctx.captured_queries) >= 1, kwargs

        with CaptureQueriesContext(connection) as ctx:
            result = cached_open_period_rows('region', [self.region.pk], entries.O3, 'month', self.midday)
        assert len(ctx.captured_queries) >= 1
        assert result == {}
