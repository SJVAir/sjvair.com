from datetime import datetime
from unittest.mock import patch

from django.conf import settings
from django.contrib.gis.geos import Point
from django.test import TestCase
from tdigest import TDigest

from camp.apps.monitors.airnow.models import AirNow
from camp.apps.monitors.purpleair.models import PurpleAir
from camp.apps.regions.models import Region
from camp.apps.summaries.aggregators import tdigest_to_dict
from camp.apps.summaries.models import BaseSummary, MonitorSummary, RegionSummary
from camp.apps.summaries.period_stats import expected_days, fill_period_statistics, period_figure
from camp.apps.summaries.peaks import day_hours
from camp.apps.summaries.periods import period_end
from camp.apps.summaries.tasks import (
    daily_monitor_summaries, monthly_monitor_summaries, monthly_region_summaries,
    quarterly_monitor_summaries, quarterly_region_summaries,
)
from camp.utils.datetime import make_aware

R = BaseSummary.Resolution


def pacific(y, m, d=1):
    return make_aware(datetime(y, m, d), settings.DEFAULT_TIMEZONE)


def _stats(mean):
    digest = TDigest()
    digest.update(mean)
    return dict(
        count=1, expected_count=1, sum_value=mean, sum_of_squares=mean * mean,
        tdigest=tdigest_to_dict(digest), minimum=mean, maximum=mean, mean=mean,
        stddev=0.0, p25=mean, p75=mean,
    )


class PeriodFigureTests(TestCase):
    def test_threshold(self):
        assert period_figure([10.0] * 23, 30) == (10.0, 23)
        assert period_figure([10.0] * 22, 30) == (None, 22)
        assert period_figure([], 31) == (None, 0)
        assert period_figure([1.0, 2.0, 3.0], 3) == (2.0, 3)

    def test_expected_days(self):
        assert expected_days(pacific(2026, 11), pacific(2026, 12)) == 30
        assert expected_days(pacific(2026, 3), pacific(2026, 4)) == 31
        assert expected_days(pacific(2026, 10), pacific(2027, 1)) == 92
        assert expected_days(pacific(2025, 12), pacific(2026, 3)) == 90
        assert expected_days(pacific(2028, 1), pacific(2029, 1)) == 366


class FillPeriodStatisticsTests(TestCase):
    fixtures = ['purple-air.yaml', 'regions.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.first()
        self.region = Region.objects.filter(boundary__isnull=False).first()

    def days(self, entry_type, field, values, start, processor='', owner=None):
        """DAILY monitor rows from `start`, one per value (None = null figure)."""
        owner = owner or self.monitor
        ts = start
        for v in values:
            MonitorSummary.objects.create(
                monitor=owner, timestamp=ts, resolution=R.DAILY, entry_type=entry_type,
                processor=processor, **_stats(v if v is not None else 0.0), **{field: v})
            ts = period_end('day', ts)

    def coarse(self, resolution, ts, entry_type, processor='', owner=None):
        return MonitorSummary.objects.create(
            monitor=owner or self.monitor, timestamp=ts, resolution=resolution,
            entry_type=entry_type, processor=processor, **_stats(1.0))

    def fill(self, start, end, **kw):
        return fill_period_statistics('monitor', None, start, end, **kw)

    def test_month_monitor(self):
        self.days('o3', 'max_1h', list(range(40, 63)) + [None] * 7, pacific(2026, 11))
        row = self.coarse(R.MONTHLY, pacific(2026, 11), 'o3')
        result = self.fill(pacific(2026, 11), pacific(2026, 12))
        row.refresh_from_db()
        assert result == {'o3': 1}
        assert row.daily_statistic_mean == sum(range(40, 63)) / 23
        assert row.daily_statistic_days == 23
        assert row.daily_statistic_expected_days == 30

    def test_below_threshold(self):
        self.days('o3', 'max_1h', [50.0] * 22 + [None] * 8, pacific(2026, 11))
        row = self.coarse(R.MONTHLY, pacific(2026, 11), 'o3')
        self.fill(pacific(2026, 11), pacific(2026, 12))
        row.refresh_from_db()
        assert (row.daily_statistic_mean, row.daily_statistic_days,
                row.daily_statistic_expected_days) == (None, 22, 30)

    def test_no_figures(self):
        self.days('o3', 'max_1h', [None] * 30, pacific(2026, 11))
        row = self.coarse(R.MONTHLY, pacific(2026, 11), 'o3')
        self.fill(pacific(2026, 11), pacific(2026, 12))
        row.refresh_from_db()
        assert (row.daily_statistic_mean, row.daily_statistic_days,
                row.daily_statistic_expected_days) == (None, 0, 30)

    def test_quarter_reads_daily_rows(self):
        values = [float(i) for i in range(80)]
        self.days('pm25', 'mean_24h', values, pacific(2026, 10))
        row = self.coarse(R.QUARTERLY, pacific(2026, 10), 'pm25')
        self.fill(pacific(2026, 10), pacific(2026, 11))
        row.refresh_from_db()
        assert row.daily_statistic_expected_days == 92
        assert row.daily_statistic_days == 80
        assert row.daily_statistic_mean == sum(values) / 80

    def test_processors_kept_apart(self):
        self.days('pm25', 'mean_24h', [10.0] * 30, pacific(2026, 11), processor='')
        self.days('pm25', 'mean_24h', [20.0] * 30, pacific(2026, 11), processor='cleaned')
        a = self.coarse(R.MONTHLY, pacific(2026, 11), 'pm25', processor='')
        b = self.coarse(R.MONTHLY, pacific(2026, 11), 'pm25', processor='cleaned')
        self.fill(pacific(2026, 11), pacific(2026, 12))
        a.refresh_from_db()
        b.refresh_from_db()
        assert a.daily_statistic_mean == 10.0
        assert b.daily_statistic_mean == 20.0

    def test_region(self):
        ts = pacific(2026, 11)
        for i in range(25):
            RegionSummary.objects.create(
                region=self.region, timestamp=ts, resolution=R.DAILY, entry_type='o3',
                max_1h=float(i), station_count=1, weight=1.0, **_stats(1.0))
            ts = period_end('day', ts)
        row = RegionSummary.objects.create(
            region=self.region, timestamp=pacific(2026, 11), resolution=R.MONTHLY,
            entry_type='o3', station_count=1, weight=1.0, **_stats(1.0))
        result = fill_period_statistics('region', None, pacific(2026, 11), pacific(2026, 12))
        row.refresh_from_db()
        assert result == {'o3': 1}
        assert row.daily_statistic_mean == 12.0
        assert (row.daily_statistic_days, row.daily_statistic_expected_days) == (25, 30)

    def test_non_peak_type_untouched(self):
        row = self.coarse(R.MONTHLY, pacific(2026, 11), 'temperature')
        assert self.fill(pacific(2026, 11), pacific(2026, 12)) == {}
        row.refresh_from_db()
        assert (row.daily_statistic_mean, row.daily_statistic_days,
                row.daily_statistic_expected_days) == (None, None, None)

    def test_scope_and_dry_run(self):
        self.days('o3', 'max_1h', [50.0] * 30, pacific(2026, 11))
        row = self.coarse(R.MONTHLY, pacific(2026, 11), 'o3')
        start, end = pacific(2026, 11), pacific(2026, 12)
        other = AirNow.objects.create(
            name='Other', position=Point(-119.5, 36.5, srid=4326), location='outside')

        assert fill_period_statistics('monitor', [other.pk], start, end) == {}
        row.refresh_from_db()
        assert row.daily_statistic_days is None

        assert self.fill(start, end, dry_run=True) == {'o3': 1}
        row.refresh_from_db()
        assert row.daily_statistic_days is None

        assert self.fill(start, end) == {'o3': 1}
        row.refresh_from_db()
        assert row.daily_statistic_mean == 50.0
        assert self.fill(start, end) == {}

    def test_dst_month_and_season(self):
        # March 2026 holds the 23-hour day; Dec 2025-Feb 2026 spans both year ends.
        self.days('o3', 'max_1h', [float(i) for i in range(31)], pacific(2026, 3))
        month = self.coarse(R.MONTHLY, pacific(2026, 3), 'o3')
        self.days('pm25', 'mean_24h', [float(i) for i in range(70)], pacific(2025, 12))
        season = self.coarse(R.SEASONAL, pacific(2025, 12), 'pm25')
        self.fill(pacific(2025, 12), pacific(2026, 4))
        month.refresh_from_db()
        season.refresh_from_db()
        assert (month.daily_statistic_expected_days, month.daily_statistic_days) == (31, 31)
        assert month.daily_statistic_mean == 15.0
        assert (season.daily_statistic_expected_days, season.daily_statistic_days) == (90, 70)
        assert season.daily_statistic_mean == 34.5


PERIOD = ('daily_statistic_mean', 'daily_statistic_days', 'daily_statistic_expected_days')


def period_values(row):
    row.refresh_from_db()
    return tuple(getattr(row, f) for f in PERIOD)


class RollupFillsTests(TestCase):
    """Each coarse rollup fills the period daily statistic after its upsert."""
    fixtures = ['purple-air.yaml', 'regions.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.first()
        self.region = Region.objects.filter(boundary__isnull=False).first()

    def daily(self, start, end, value=50.0):
        ts = start
        while ts < end:
            MonitorSummary.objects.create(
                monitor=self.monitor, timestamp=ts, resolution=R.DAILY, entry_type='o3',
                processor='', is_complete=True, max_1h=value, **_stats(value))
            RegionSummary.objects.create(
                region=self.region, timestamp=ts, resolution=R.DAILY, entry_type='o3',
                station_count=1, weight=1.0, max_1h=value, **_stats(value))
            ts = period_end('day', ts)

    def monthly(self, kind, ts):
        model, owner = (MonitorSummary, {'monitor': self.monitor}) if kind == 'monitor' \
            else (RegionSummary, {'region': self.region})
        return model.objects.get(resolution=R.MONTHLY, entry_type='o3', timestamp=ts, **owner)

    def test_monthly_rollup_fills(self):
        nov = pacific(2026, 11)
        self.daily(nov, pacific(2026, 12))
        monthly_monitor_summaries.call_local(month_start=nov)
        monthly_region_summaries.call_local(month_start=nov)
        for kind in ('monitor', 'region'):
            assert period_values(self.monthly(kind, nov)) == (50.0, 30, 30)

    def test_quarterly_rollup_fills(self):
        oct_, nov, dec = pacific(2026, 10), pacific(2026, 11), pacific(2026, 12)
        self.daily(oct_, pacific(2027, 1))
        for month in (oct_, nov, dec):
            monthly_monitor_summaries.call_local(month_start=month)
            monthly_region_summaries.call_local(month_start=month)
        quarterly_monitor_summaries.call_local(quarter_start=oct_)
        quarterly_region_summaries.call_local(quarter_start=oct_)
        assert period_values(MonitorSummary.objects.get(
            monitor=self.monitor, resolution=R.QUARTERLY, entry_type='o3', timestamp=oct_)) == (50.0, 92, 92)
        assert period_values(RegionSummary.objects.get(
            region=self.region, resolution=R.QUARTERLY, entry_type='o3', timestamp=oct_)) == (50.0, 92, 92)

    def test_reroll_keeps_then_rewrites(self):
        nov = pacific(2026, 11)
        self.daily(nov, pacific(2026, 12))
        monthly_monitor_summaries.call_local(month_start=nov)
        row = self.monthly('monitor', nov)
        assert period_values(row) == (50.0, 30, 30)
        MonitorSummary.objects.filter(
            monitor=self.monitor, resolution=R.DAILY, entry_type='o3', timestamp=nov,
        ).update(max_1h=80.0)
        monthly_monitor_summaries.call_local(month_start=nov)
        assert period_values(row) == (51.0, 30, 30)


class CORefreshTests(TestCase):
    """The next night's max_8h refresh refills the periods its day ends."""
    fixtures = ['purple-air.yaml', 'regions.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.first()

    def hourly(self, hours, value):
        for hour in hours:
            MonitorSummary.objects.create(
                monitor=self.monitor, timestamp=hour, resolution=R.HOURLY, entry_type='co',
                processor='', is_complete=True, **_stats(value))

    def test_last_day_refresh_refills_month(self):
        nov, nov30, dec1 = pacific(2026, 11), pacific(2026, 11, 30), pacific(2026, 12)
        ts = nov
        while ts < nov30:
            MonitorSummary.objects.create(
                monitor=self.monitor, timestamp=ts, resolution=R.DAILY, entry_type='co',
                processor='', is_complete=True, max_8h=1.0, **_stats(1.0))
            ts = period_end('day', ts)
        self.hourly(day_hours(nov30), 1.0)
        daily_monitor_summaries(day=nov30)
        monthly_monitor_summaries.call_local(month_start=nov)
        month = MonitorSummary.objects.get(
            monitor=self.monitor, resolution=R.MONTHLY, entry_type='co', timestamp=nov)
        assert period_values(month)[0] == 1.0  # Nov 30 provisional: 1.0

        # Dec 1 morning: the windows that start late on Nov 30 now see 20s.
        self.hourly(day_hours(dec1)[:8], 20.0)
        daily_monitor_summaries(day=dec1)

        last = MonitorSummary.objects.get(
            monitor=self.monitor, resolution=R.DAILY, entry_type='co', timestamp=nov30)
        assert last.max_8h == 17.625
        figures = [v for v in MonitorSummary.objects.filter(
            monitor=self.monitor, resolution=R.DAILY, entry_type='co',
            timestamp__gte=nov, timestamp__lt=dec1,
        ).values_list('max_8h', flat=True) if v is not None]
        mean, days, expected = period_values(month)
        assert (days, expected) == (len(figures), 30)
        assert mean == sum(figures) / len(figures)
        assert mean > 1.0

    def test_refresh_fills_only_periods_ending_with_the_day(self):
        with patch('camp.apps.summaries.tasks.fill_period_statistics', return_value={}) as fill:
            daily_monitor_summaries(day=pacific(2026, 11, 16))
            assert fill.call_count == 0
            daily_monitor_summaries(day=pacific(2026, 12))
        # Nov 30 ends November and the Sep-Nov season, not Q4 or the year.
        calls = {tuple(c.kwargs['resolutions']): c.args for c in fill.call_args_list}
        assert calls == {
            ('month',): ('monitor', None, pacific(2026, 11), pacific(2026, 12)),
            ('season',): ('monitor', None, pacific(2026, 9), pacific(2026, 12)),
        }
        for c in fill.call_args_list:
            assert [m.entry_type for m in c.kwargs['entry_models']] == ['co']
