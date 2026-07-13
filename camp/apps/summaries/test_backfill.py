from datetime import datetime, timedelta

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone
import pytest

from camp.utils.datetime import make_aware
from camp.apps.summaries.models import BaseSummary
from camp.apps.summaries.backfill import (
    chunk_start_for,
    hour_range,
    iter_chunk_days,
    daily_rollup_window,
    higher_rollup_windows,
)
from camp.apps.entries.models import PM25
from camp.apps.monitors.bam.models import BAM1022
from camp.apps.monitors.models import Monitor
from camp.apps.monitors.purpleair.models import PurpleAir
from camp.apps.regions.models import Region
from camp.apps.summaries.models import BaseSummary, MonitorSummary, RegionSummary, SummaryBackfillJob
from camp.apps.summaries.backfill import (
    backfill_monitor_hours,
    backfill_region_hours,
    monitors_with_data_in,
    regions_with_monitors,
)


def _day(y, m, d):
    return make_aware(datetime(y, m, d), settings.DEFAULT_TIMEZONE)


class ChunkStartForTests(TestCase):
    def test_steps_back_seven_days(self):
        cursor = _day(2023, 7, 15)
        range_start = _day(2020, 1, 1)
        assert chunk_start_for(cursor, range_start) == cursor - timedelta(days=7)

    def test_clamps_to_range_start(self):
        cursor = _day(2020, 1, 4)
        range_start = _day(2020, 1, 1)
        assert chunk_start_for(cursor, range_start) == range_start


class HourRangeTests(TestCase):
    def test_yields_each_hour_exclusive_of_end(self):
        start = _day(2023, 1, 1)
        end = start + timedelta(hours=3)
        hours = list(hour_range(start, end))
        assert hours == [start, start + timedelta(hours=1), start + timedelta(hours=2)]


class IterChunkDaysTests(TestCase):
    def test_yields_each_day_exclusive_of_end(self):
        start = _day(2023, 1, 1)
        end = start + timedelta(days=3)
        days = list(iter_chunk_days(start, end))
        assert days == [start, start + timedelta(days=1), start + timedelta(days=2)]


class DailyRollupWindowTests(TestCase):
    def test_returns_daily_window(self):
        day = _day(2023, 7, 15)
        target, source, window_start, window_end = daily_rollup_window(day)
        assert target == BaseSummary.Resolution.DAILY
        assert source == BaseSummary.Resolution.HOURLY
        assert window_start == day
        assert window_end == day + timedelta(days=1)


class HigherRollupWindowsTests(TestCase):
    def test_mid_month_day_has_no_higher_windows(self):
        assert higher_rollup_windows(_day(2023, 7, 15)) == []

    def test_ordinary_month_start_rolls_up_month_only(self):
        windows = higher_rollup_windows(_day(2023, 8, 1))
        resolutions = [w[0] for w in windows]
        assert resolutions == [BaseSummary.Resolution.MONTHLY]

    def test_quarter_start_month_cascades_to_quarterly(self):
        windows = higher_rollup_windows(_day(2023, 7, 1))
        resolutions = [w[0] for w in windows]
        assert BaseSummary.Resolution.MONTHLY in resolutions
        assert BaseSummary.Resolution.QUARTERLY in resolutions
        assert BaseSummary.Resolution.SEASONAL not in resolutions
        assert BaseSummary.Resolution.YEARLY not in resolutions

    def test_season_start_month_cascades_to_seasonal(self):
        windows = higher_rollup_windows(_day(2023, 6, 1))
        resolutions = [w[0] for w in windows]
        assert BaseSummary.Resolution.SEASONAL in resolutions

    def test_december_is_season_start_but_not_quarter_start(self):
        windows = higher_rollup_windows(_day(2023, 12, 1))
        resolutions = [w[0] for w in windows]
        assert BaseSummary.Resolution.SEASONAL in resolutions
        assert BaseSummary.Resolution.QUARTERLY not in resolutions

    def test_january_cascades_to_quarterly_and_yearly(self):
        windows = higher_rollup_windows(_day(2023, 1, 1))
        resolutions = [w[0] for w in windows]
        assert BaseSummary.Resolution.MONTHLY in resolutions
        assert BaseSummary.Resolution.QUARTERLY in resolutions
        assert BaseSummary.Resolution.YEARLY in resolutions

    def test_quarterly_window_spans_three_months(self):
        windows = higher_rollup_windows(_day(2023, 7, 1))
        quarterly = next(w for w in windows if w[0] == BaseSummary.Resolution.QUARTERLY)
        _, _, window_start, window_end = quarterly
        assert window_start == _day(2023, 7, 1)
        assert window_end == _day(2023, 10, 1)

    def test_yearly_window_spans_twelve_months(self):
        windows = higher_rollup_windows(_day(2023, 1, 1))
        yearly = next(w for w in windows if w[0] == BaseSummary.Resolution.YEARLY)
        _, _, window_start, window_end = yearly
        assert window_start == _day(2023, 1, 1)
        assert window_end == _day(2024, 1, 1)


class BackfillMonitorHoursTests(TestCase):
    fixtures = ['purple-air.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.first()
        self.start = timezone.now().replace(minute=0, second=0, microsecond=0) - timedelta(hours=3)
        self.end = self.start + timedelta(hours=2)

    def _make_entry(self, hour_offset, value):
        return PM25.objects.create(
            monitor=self.monitor,
            timestamp=self.start + timedelta(hours=hour_offset, minutes=5),
            stage=PM25.Stage.RAW,
            processor='',
            value=value,
            location=self.monitor.location,
        )

    def test_creates_one_summary_per_hour_with_data(self):
        self._make_entry(0, 10.0)
        self._make_entry(1, 20.0)
        count = backfill_monitor_hours(self.monitor, self.start, self.end, [PM25])
        assert count == 2
        assert MonitorSummary.objects.filter(monitor=self.monitor, resolution=BaseSummary.Resolution.HOURLY).count() == 2

    def test_skips_hours_with_no_entries(self):
        self._make_entry(0, 10.0)
        backfill_monitor_hours(self.monitor, self.start, self.end, [PM25])
        assert MonitorSummary.objects.count() == 1

    def test_excludes_entries_outside_range(self):
        self._make_entry(-1, 999.0)  # before self.start
        backfill_monitor_hours(self.monitor, self.start, self.end, [PM25])
        assert MonitorSummary.objects.count() == 0

    def test_is_idempotent_on_rerun(self):
        self._make_entry(0, 10.0)
        backfill_monitor_hours(self.monitor, self.start, self.end, [PM25])
        backfill_monitor_hours(self.monitor, self.start, self.end, [PM25])
        assert MonitorSummary.objects.count() == 1


class MonitorsWithDataInTests(TestCase):
    fixtures = ['purple-air.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.first()
        self.start = timezone.now().replace(minute=0, second=0, microsecond=0) - timedelta(hours=2)
        self.end = self.start + timedelta(hours=1)

    def test_includes_monitor_with_entry_in_range(self):
        PM25.objects.create(
            monitor=self.monitor, timestamp=self.start + timedelta(minutes=5),
            stage=PM25.Stage.RAW, processor='', value=10.0, location=self.monitor.location,
        )
        assert self.monitor.pk in monitors_with_data_in(self.start, self.end, [PM25])

    def test_excludes_monitor_with_no_entries(self):
        assert self.monitor.pk not in monitors_with_data_in(self.start, self.end, [PM25])


class RegionsWithMonitorsTests(TestCase):
    fixtures = ['purple-air.yaml', 'regions.yaml']

    def test_returns_region_containing_a_monitor(self):
        region = Region.objects.filter(boundary__isnull=False).first()
        if not region:
            self.skipTest('no region with boundary in fixtures')
        monitor = PurpleAir.objects.first()
        monitor.position = region.boundary.geometry.centroid
        monitor.save()
        assert region.pk in regions_with_monitors()

    def test_excludes_region_with_no_monitors(self):
        region = Region.objects.filter(boundary__isnull=False).first()
        if not region:
            self.skipTest('no region with boundary in fixtures')
        monitor = PurpleAir.objects.first()
        monitor.position = None
        monitor.save()
        assert region.pk not in regions_with_monitors()

class BackfillRegionHoursTests(TestCase):
    fixtures = ['purple-air.yaml', 'regions.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.first()
        self.region = Region.objects.filter(boundary__isnull=False).first()
        if not self.region:
            self.skipTest('no region with boundary in fixtures')
        self.monitor.position = self.region.boundary.geometry.centroid
        self.monitor.save()
        self.hour = timezone.now().replace(minute=0, second=0, microsecond=0) - timedelta(hours=1)
        MonitorSummary.objects.create(
            monitor=self.monitor, timestamp=self.hour,
            resolution=BaseSummary.Resolution.HOURLY, entry_type='pm25', processor='',
            count=10, expected_count=30, sum_value=200.0, sum_of_squares=4000.0,
            minimum=20.0, maximum=20.0, mean=20.0, stddev=0.0, p25=20.0, p75=20.0,
            tdigest={'C': [[20.0, 10]], 'n': 10}, is_complete=False,
        )

    def test_creates_region_summary_from_monitor_summary(self):
        monitor_grades = {self.monitor.pk: Monitor.Grade.LCS}
        count = backfill_region_hours(self.region, [self.hour], monitor_grades)
        assert count == 1
        assert RegionSummary.objects.filter(region=self.region, timestamp=self.hour).exists()

    def test_skips_hours_with_no_monitor_summaries(self):
        monitor_grades = {self.monitor.pk: Monitor.Grade.LCS}
        other_hour = self.hour - timedelta(hours=5)
        count = backfill_region_hours(self.region, [other_hour], monitor_grades)
        assert count == 0


class SummaryBackfillJobTests(TestCase):
    def _make_job(self, **kwargs):
        now = timezone.now()
        defaults = dict(
            cursor=now,
            range_start=now - timedelta(days=365),
            range_end=now,
        )
        defaults.update(kwargs)
        return SummaryBackfillJob.objects.create(**defaults)

    def test_defaults(self):
        job = self._make_job()
        assert job.state == SummaryBackfillJob.State.RUNNING
        assert job.phase == SummaryBackfillJob.Phase.IDLE
        assert job.pending_tasks == 0
        assert job.batch_id == 0
        assert job.consecutive_failures == 0
        assert job.last_error == ''
        assert job.chunk_start is None
        assert job.locked_at is None
        assert job.sqid


class BackfillSummariesCommandTests(TestCase):
    def _run(self, *args):
        call_command('backfill_summaries', *args, stdout=open('/dev/null', 'w'))

    def test_start_creates_running_idle_job(self):
        self._run('start', '--from=2020-01-01', '--to=2020-02-01')
        job = SummaryBackfillJob.objects.get()
        assert job.state == SummaryBackfillJob.State.RUNNING
        assert job.phase == SummaryBackfillJob.Phase.IDLE
        assert job.range_start == make_aware(datetime(2020, 1, 1), settings.DEFAULT_TIMEZONE)
        assert job.range_end == make_aware(datetime(2020, 2, 1), settings.DEFAULT_TIMEZONE)
        assert job.cursor == job.range_end

    def test_start_requires_from(self):
        with pytest.raises((CommandError, SystemExit)):
            self._run('start')

    def test_start_refuses_second_job_without_force(self):
        self._run('start', '--from=2020-01-01', '--to=2020-02-01')
        with pytest.raises((CommandError, SystemExit)):
            self._run('start', '--from=2019-01-01', '--to=2019-02-01')

    def test_start_force_replaces_existing_job(self):
        self._run('start', '--from=2020-01-01', '--to=2020-02-01')
        self._run('start', '--from=2019-01-01', '--to=2019-02-01', '--force')
        job = SummaryBackfillJob.objects.get()
        assert job.range_start == make_aware(datetime(2019, 1, 1), settings.DEFAULT_TIMEZONE)

    def test_status_with_no_job_does_not_raise(self):
        self._run('status')

    def test_status_with_job_does_not_raise(self):
        self._run('start', '--from=2020-01-01', '--to=2020-02-01')
        self._run('status')

    def test_cancel_sets_state_done(self):
        self._run('start', '--from=2020-01-01', '--to=2020-02-01')
        self._run('cancel')
        job = SummaryBackfillJob.objects.get()
        assert job.state == SummaryBackfillJob.State.DONE

    def test_cancel_with_no_active_job_does_not_raise(self):
        self._run('cancel')
