from datetime import datetime, timedelta, timezone as dt_timezone
from unittest.mock import patch

from django.conf import settings
from django.contrib.gis.geos import Point
from django.test import TestCase

from camp.apps.monitors.airnow.models import AirNow
from camp.apps.monitors.purpleair.models import PurpleAir
from camp.apps.regions.models import Region
from camp.apps.summaries import tasks as summary_tasks
from camp.apps.summaries.current_periods import roll_current_periods
from camp.apps.summaries.models import BaseSummary, MonitorSummary, RegionSummary
from camp.apps.summaries.periods import period_end
from camp.apps.summaries.tasks import rollup_monitor_summaries, rollup_region_summaries
from camp.apps.summaries.test_period_stats import _stats, freeze_fill_clock
from camp.utils.datetime import make_aware

R = BaseSummary.Resolution

STAT_FIELDS = (
    'count', 'expected_count', 'sum_value', 'sum_of_squares', 'minimum', 'maximum',
    'mean', 'stddev', 'p25', 'p75', 'tdigest', 'is_complete', 'is_partial',
    'daily_statistic_mean', 'daily_statistic_days', 'daily_statistic_expected_days',
)


def pacific(y, m, d=1, *rest):
    return make_aware(datetime(y, m, d, *rest), settings.DEFAULT_TIMEZONE)


def values_of(row):
    row.refresh_from_db()
    return {f: getattr(row, f) for f in STAT_FIELDS}


class CurrentPeriodsTests(TestCase):
    fixtures = ['purple-air.yaml', 'regions.yaml']

    def setUp(self):
        # The regular rollups' fill (no `now`) reads the clock; give it one after the fixtures.
        freeze_fill_clock(self)
        self.monitor = PurpleAir.objects.first()
        self.region = Region.objects.filter(boundary__isnull=False).first()

    def other_monitor(self):
        return AirNow.objects.create(
            name='Other', position=Point(-119.5, 36.5, srid=4326), location='outside')

    def daily(self, start, end, monitor=None, entry_type='o3', field='max_1h'):
        """Monitor DAILY rows on each day in [start, end), with varied values."""
        monitor = monitor or self.monitor
        ts, i = start, 0
        while ts < end:
            value = 30.0 + (i % 17)
            MonitorSummary.objects.create(
                monitor=monitor, timestamp=ts, resolution=R.DAILY, entry_type=entry_type,
                processor='', is_complete=True, **{field: value}, **_stats(value))
            ts, i = period_end('day', ts), i + 1

    def region_daily(self, start, end):
        ts, i = start, 0
        while ts < end:
            value = 30.0 + (i % 13)
            RegionSummary.objects.create(
                region=self.region, timestamp=ts, resolution=R.DAILY, entry_type='o3',
                station_count=1 + i % 3, weight=1.0, max_1h=value, **_stats(value))
            ts, i = period_end('day', ts), i + 1

    def row(self, resolution, ts, monitor=None, entry_type='o3'):
        return MonitorSummary.objects.get(
            monitor=monitor or self.monitor, resolution=resolution, timestamp=ts,
            entry_type=entry_type, processor='')

    def run_at(self, now, **kw):
        kw.setdefault('clock', lambda: now)
        return roll_current_periods('monitor', now=now, **kw)

    def test_writes_month_through_yesterday_partial(self):
        nov = pacific(2026, 11)
        # A row for today (if one existed) is left out: the month runs through yesterday.
        self.daily(nov, pacific(2026, 11, 19))
        result = self.run_at(pacific(2026, 11, 18, 2, 15))

        month = self.row(R.MONTHLY, nov)
        days = MonitorSummary.objects.filter(
            monitor=self.monitor, resolution=R.DAILY, entry_type='o3',
            timestamp__gte=nov, timestamp__lt=pacific(2026, 11, 18))
        assert month.is_partial is True
        assert month.count == sum(d.count for d in days) == 17
        assert month.daily_statistic_expected_days == 17
        assert month.daily_statistic_days == 17
        assert result['stopped'] is False
        assert result['rolled']['month'] == 1

    def test_quarter_season_year_include_partial_month(self):
        sep, oct_, nov = pacific(2026, 9), pacific(2026, 10), pacific(2026, 11)
        self.daily(sep, pacific(2026, 11, 18))
        rollup_monitor_summaries(R.MONTHLY, R.DAILY, sep, oct_)
        rollup_monitor_summaries(R.MONTHLY, R.DAILY, oct_, nov)
        self.run_at(pacific(2026, 11, 18, 2, 15))

        months = {
            m.timestamp: m.count for m in MonitorSummary.objects.filter(
                monitor=self.monitor, resolution=R.MONTHLY, entry_type='o3')
        }
        assert self.row(R.MONTHLY, nov).is_partial is True
        cases = [
            (R.QUARTERLY, oct_, [oct_, nov], 48),
            (R.SEASONAL, sep, [sep, oct_, nov], 78),
            (R.YEARLY, pacific(2026, 1), [sep, oct_, nov], 321),
        ]
        for resolution, start, parts, expected in cases:
            row = self.row(resolution, start)
            assert row.is_partial is True, resolution
            assert row.count == sum(months[p] for p in parts), resolution
            assert row.daily_statistic_expected_days == expected, resolution

    def test_first_night_writes_ended_period_in_full(self):
        nov, dec = pacific(2026, 11), pacific(2026, 12)
        self.daily(nov, dec)
        self.run_at(pacific(2026, 12, 1, 2, 15))
        month = self.row(R.MONTHLY, nov)
        written = values_of(month)
        assert written['is_partial'] is False
        assert written['daily_statistic_expected_days'] == 30

        rollup_monitor_summaries(R.MONTHLY, R.DAILY, nov, dec)
        assert values_of(month) == written
        assert not MonitorSummary.objects.filter(resolution=R.MONTHLY, timestamp=dec).exists()

    def test_january_first_mixed_periods(self):
        dec = pacific(2026, 12)
        self.daily(dec, pacific(2027, 1))
        self.run_at(pacific(2027, 1, 1, 2, 15))
        for resolution, start in ((R.MONTHLY, dec), (R.QUARTERLY, pacific(2026, 10)),
                                  (R.YEARLY, pacific(2026, 1))):
            assert self.row(resolution, start).is_partial is False, resolution
        winter = self.row(R.SEASONAL, dec)
        assert winter.is_partial is True
        assert winter.daily_statistic_expected_days == 31
        assert not MonitorSummary.objects.filter(timestamp=pacific(2027, 1)).exclude(
            resolution__in=[R.HOURLY, R.DAILY]).exists()

    def test_only_owners_with_yesterday_rolled(self):
        nov = pacific(2026, 11)
        other = self.other_monitor()
        self.daily(nov, pacific(2026, 11, 18))
        self.daily(nov, pacific(2026, 11, 17), monitor=other)
        self.run_at(pacific(2026, 11, 17, 2, 15))
        before = values_of(self.row(R.MONTHLY, nov, monitor=other))

        # Change one of the other monitor's inputs: a re-roll would show it.
        MonitorSummary.objects.filter(
            monitor=other, resolution=R.DAILY, timestamp=pacific(2026, 11, 5)).update(count=99)
        result = self.run_at(pacific(2026, 11, 18, 2, 15))

        assert result['rolled']['month'] == 1
        after = values_of(self.row(R.MONTHLY, nov, monitor=other))
        refreshed = ('daily_statistic_expected_days', 'daily_statistic_mean')
        assert {k: v for k, v in after.items() if k not in refreshed} == \
            {k: v for k, v in before.items() if k not in refreshed}
        assert after['daily_statistic_expected_days'] == 17
        assert self.row(R.MONTHLY, nov).daily_statistic_expected_days == 17

    def test_unchanged_owner_expected_days_move(self):
        nov = pacific(2026, 11)
        other = self.other_monitor()
        self.daily(nov, pacific(2026, 11, 18))

        def partial(entry_type, days, **extra):
            return MonitorSummary.objects.create(
                monitor=other, timestamp=nov, resolution=R.MONTHLY, entry_type=entry_type,
                processor='', is_partial=True, **_stats(1.0), **extra)

        short = partial('o3', 12, daily_statistic_mean=40.0, daily_statistic_days=12,
                        daily_statistic_expected_days=16)
        enough = partial('no2', 13, daily_statistic_mean=41.0, daily_statistic_days=13,
                         daily_statistic_expected_days=16)
        weather = partial('temperature', 0)
        result = self.run_at(pacific(2026, 11, 18, 2, 15))

        short.refresh_from_db()
        enough.refresh_from_db()
        weather.refresh_from_db()
        assert (short.daily_statistic_expected_days, short.daily_statistic_mean) == (17, None)
        assert (enough.daily_statistic_expected_days, enough.daily_statistic_mean) == (17, 41.0)
        assert weather.daily_statistic_expected_days is None
        assert result['refreshed']['month'] == 2

    def test_nobody_reported_still_refreshes(self):
        nov = pacific(2026, 11)
        self.daily(nov, pacific(2026, 11, 17))  # last row Nov 16: nothing yesterday
        self.run_at(pacific(2026, 11, 17, 2, 15))
        month = self.row(R.MONTHLY, nov)
        before = values_of(month)
        assert before['daily_statistic_expected_days'] == 16

        result = self.run_at(pacific(2026, 11, 18, 2, 15))
        after = values_of(month)
        assert result['rolled'] == {}
        assert result['refreshed']['month'] == 1
        assert after['daily_statistic_expected_days'] == 17
        assert after['count'] == before['count']

    def test_stops_when_midnight_passes(self):
        nov, dec = pacific(2026, 11), pacific(2026, 12)
        self.daily(nov, dec)
        rollup_monitor_summaries(R.MONTHLY, R.DAILY, nov, dec)
        month = self.row(R.MONTHLY, nov)
        final = values_of(month)
        rows = MonitorSummary.objects.count()

        result = self.run_at(pacific(2026, 11, 30, 2, 15), clock=lambda: pacific(2026, 12, 1, 0, 5))

        assert values_of(month) == final
        assert result['stopped'] is True
        assert MonitorSummary.objects.count() == rows

    def test_stops_inside_a_rollup(self):
        nov, dec = pacific(2026, 11), pacific(2026, 12)
        self.daily(nov, dec)
        rollup_monitor_summaries(R.MONTHLY, R.DAILY, nov, dec)
        month = self.row(R.MONTHLY, nov)
        final = values_of(month)
        # The run's own check passes; midnight passes before the rollup's upsert.
        times = iter([pacific(2026, 11, 30, 2, 15)])
        result = self.run_at(
            pacific(2026, 11, 30, 2, 15), clock=lambda: next(times, pacific(2026, 12, 1, 0, 5)))

        assert values_of(month) == final
        assert result['stopped'] is True
        assert result['rolled'] == {}

    def test_period_starting_today_gets_no_row(self):
        self.daily(pacific(2026, 11), pacific(2026, 12, 2))
        self.run_at(pacific(2026, 12, 1, 2, 15))
        assert not MonitorSummary.objects.filter(
            timestamp=pacific(2026, 12), resolution__in=[R.MONTHLY, R.SEASONAL]).exists()
        assert self.row(R.MONTHLY, pacific(2026, 11)).is_partial is False

    def test_ids_roll_exactly_those_owners(self):
        nov = pacific(2026, 11)
        other = self.other_monitor()
        self.daily(nov, pacific(2026, 11, 10))  # nothing yesterday
        stale = MonitorSummary.objects.create(
            monitor=other, timestamp=nov, resolution=R.MONTHLY, entry_type='o3', processor='',
            is_partial=True, daily_statistic_days=5, daily_statistic_expected_days=16,
            daily_statistic_mean=1.0, **_stats(1.0))
        result = self.run_at(pacific(2026, 11, 18, 2, 15), ids=[self.monitor.pk])

        month = self.row(R.MONTHLY, nov)
        assert month.is_partial is True
        assert month.count == 9
        assert month.daily_statistic_expected_days == 17
        assert result['rolled']['month'] == 1
        assert result['refreshed'] == {}
        stale.refresh_from_db()
        assert stale.daily_statistic_expected_days == 16

    def test_coarse_partial_then_full_clears_is_partial(self):
        nov, dec = pacific(2026, 11), pacific(2026, 12)
        self.daily(nov, dec)
        self.run_at(pacific(2026, 11, 18, 2, 15))
        month = self.row(R.MONTHLY, nov)
        assert month.is_partial is True
        rollup_monitor_summaries(R.MONTHLY, R.DAILY, nov, dec)
        month.refresh_from_db()
        assert month.is_partial is False
        assert month.count == 30
        assert month.daily_statistic_expected_days == 30

    def test_regions_twin(self):
        nov = pacific(2026, 11)
        self.region_daily(nov, pacific(2026, 11, 18))
        now = pacific(2026, 11, 18, 2, 15)
        result = roll_current_periods('region', now=now, clock=lambda: now)

        row = RegionSummary.objects.get(
            region=self.region, resolution=R.MONTHLY, timestamp=nov, entry_type='o3')
        assert row.is_partial is True
        assert row.station_count == 3
        assert row.count == 17
        assert row.daily_statistic_expected_days == 17
        assert result['rolled']['month'] == 1
        for resolution, start in ((R.QUARTERLY, pacific(2026, 10)), (R.SEASONAL, pacific(2026, 9)),
                                  (R.YEARLY, pacific(2026, 1))):
            coarse = RegionSummary.objects.get(
                region=self.region, resolution=resolution, timestamp=start, entry_type='o3')
            assert coarse.is_partial is True, resolution
            assert coarse.station_count == 3, resolution

    def test_kind_must_be_known(self):
        with self.assertRaises(ValueError):
            roll_current_periods('station', now=pacific(2026, 11, 18, 2, 15))


class CurrentPeriodTaskScheduleTests(TestCase):
    def validates(self, task, instant):
        # Huey calls the schedule with a naive UTC datetime.
        naive_utc = instant.astimezone(dt_timezone.utc).replace(tzinfo=None)
        return task.task_class().validate_datetime(naive_utc)

    def test_tasks_scheduled(self):
        monitor_task = summary_tasks.current_monitor_periods
        region_task = summary_tasks.current_region_periods
        for day in (pacific(2026, 11, 18), pacific(2026, 7, 18)):
            at = lambda h, m: day + timedelta(hours=h, minutes=m)  # noqa: E731
            assert self.validates(monitor_task, at(2, 15))
            assert not self.validates(monitor_task, at(2, 14))
            assert not self.validates(monitor_task, at(2, 20))
            assert self.validates(region_task, at(2, 20))
            assert not self.validates(region_task, at(2, 14))
            assert not self.validates(region_task, at(2, 15))
            # Only the Pacific 02:xx, not the other UTC hour the crontab matches.
            assert not self.validates(monitor_task, at(3, 15))

    def test_tasks_call_roll_current_periods(self):
        with patch('camp.apps.summaries.tasks.roll_current_periods') as roll:
            summary_tasks.current_monitor_periods.call_local()
            summary_tasks.current_region_periods.call_local(region_ids=[1])
        assert roll.call_args_list[0].args == ('monitor', None)
        assert roll.call_args_list[1].args == ('region', [1])
