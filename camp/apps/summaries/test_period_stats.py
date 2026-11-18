from datetime import datetime

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
from camp.apps.summaries.periods import period_end
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
