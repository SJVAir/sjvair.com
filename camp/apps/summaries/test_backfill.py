from datetime import datetime, timedelta

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.utils import timezone
import pytest

from camp.utils.datetime import make_aware
from camp.apps.summaries.backfill import (
    chunk_start_for,
    hour_range,
    iter_chunk_days,
    daily_rollup_window,
    higher_rollup_windows,
)
from camp.apps.entries.models import PM25
from camp.apps.monitors.models import Monitor
from camp.apps.monitors.purpleair.models import PurpleAir
from camp.apps.regions.models import Region
from camp.apps.summaries.models import BaseSummary, MonitorSummary, RegionSummary, SummaryBackfillJob
from camp.apps.summaries.tasks import backfill_monitor_chunk, backfill_region_chunk
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
        # purple-air.yaml defines several monitors clustered at nearly the
        # same real position — null all of them, not just .first(), so this
        # region is genuinely monitor-free regardless of which one .first()
        # would otherwise have singled out. A bulk .update() doesn't work
        # here: Django's multi-table-inheritance UPDATE path re-runs
        # get_prep_value() on already-resolved PKs, which django_smalluuid's
        # SmallUUIDField.to_python() can't handle — so save() each instance.
        for monitor in PurpleAir.objects.all():
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


class BackfillMonitorChunkTaskTests(TestCase):
    fixtures = ['purple-air.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.first()
        now = timezone.now()
        self.chunk_start = now.replace(minute=0, second=0, microsecond=0) - timedelta(hours=2)
        self.chunk_end = self.chunk_start + timedelta(hours=1)
        self.job = SummaryBackfillJob.objects.create(
            cursor=self.chunk_end, range_start=self.chunk_start - timedelta(days=1), range_end=self.chunk_end,
            phase=SummaryBackfillJob.Phase.MONITORS, pending_tasks=1, batch_id=1,
        )
        PM25.objects.create(
            monitor=self.monitor, timestamp=self.chunk_start + timedelta(minutes=5),
            stage=PM25.Stage.RAW, processor='', value=10.0, location=self.monitor.location,
        )

    def test_creates_summary_and_decrements_pending_tasks(self):
        backfill_monitor_chunk(self.job.pk, str(self.monitor.pk), self.chunk_start, self.chunk_end, 1)
        assert MonitorSummary.objects.filter(monitor=self.monitor).exists()
        self.job.refresh_from_db()
        assert self.job.pending_tasks == 0

    def test_stale_batch_id_does_not_decrement(self):
        backfill_monitor_chunk(self.job.pk, str(self.monitor.pk), self.chunk_start, self.chunk_end, 999)
        # Summary is still written — computation isn't fenced, only the counter is.
        assert MonitorSummary.objects.filter(monitor=self.monitor).exists()
        self.job.refresh_from_db()
        assert self.job.pending_tasks == 1

    def test_wrong_phase_does_not_decrement(self):
        self.job.phase = SummaryBackfillJob.Phase.REGIONS
        self.job.save(update_fields=['phase'])
        backfill_monitor_chunk(self.job.pk, str(self.monitor.pk), self.chunk_start, self.chunk_end, 1)
        self.job.refresh_from_db()
        assert self.job.pending_tasks == 1


class BackfillRegionChunkTaskTests(TestCase):
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
            resolution=MonitorSummary.Resolution.HOURLY, entry_type='pm25', processor='',
            count=10, expected_count=30, sum_value=200.0, sum_of_squares=4000.0,
            minimum=20.0, maximum=20.0, mean=20.0, stddev=0.0, p25=20.0, p75=20.0,
            tdigest={'C': [[20.0, 10]], 'n': 10}, is_complete=False,
        )

        self.job = SummaryBackfillJob.objects.create(
            cursor=self.hour + timedelta(hours=1), range_start=self.hour - timedelta(days=1),
            range_end=self.hour + timedelta(hours=1),
            phase=SummaryBackfillJob.Phase.REGIONS, pending_tasks=1, batch_id=1,
        )

    def test_creates_region_summary_and_decrements_pending_tasks(self):
        backfill_region_chunk(self.job.pk, str(self.region.pk), self.hour, self.hour + timedelta(hours=1), 1)
        assert RegionSummary.objects.filter(region=self.region).exists()
        self.job.refresh_from_db()
        assert self.job.pending_tasks == 0


from unittest.mock import patch

from camp.apps.summaries.tasks import backfill_summaries_tick


class BackfillSummariesTickClaimingTests(TestCase):
    def _make_job(self, **kwargs):
        now = timezone.now().replace(minute=0, second=0, microsecond=0)
        defaults = dict(cursor=now, range_start=now - timedelta(days=30), range_end=now)
        defaults.update(kwargs)
        return SummaryBackfillJob.objects.create(**defaults)

    def test_does_nothing_when_no_running_job(self):
        self._make_job(state=SummaryBackfillJob.State.DONE)
        backfill_summaries_tick()
        # No exception, and the DONE job is untouched.
        job = SummaryBackfillJob.objects.get()
        assert job.state == SummaryBackfillJob.State.DONE

    def test_skips_job_with_recent_lock(self):
        job = self._make_job(locked_at=timezone.now())
        with self.captureOnCommitCallbacks(execute=True):
            backfill_summaries_tick()
        job.refresh_from_db()
        # Still idle/batch_id 0 — the tick declined to claim a freshly-locked job.
        assert job.batch_id == 0

    def test_claims_job_with_stale_lock(self):
        job = self._make_job(locked_at=timezone.now() - timedelta(minutes=5))
        with self.captureOnCommitCallbacks(execute=True):
            backfill_summaries_tick()
        job.refresh_from_db()
        assert job.batch_id == 1


class BackfillSummariesTickDispatchMonitorsTests(TestCase):
    fixtures = ['purple-air.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.first()
        now = timezone.now().replace(minute=0, second=0, microsecond=0)
        self.job = SummaryBackfillJob.objects.create(
            cursor=now, range_start=now - timedelta(days=30), range_end=now,
        )

    def test_idle_job_with_data_dispatches_monitor_batch(self):
        PM25.objects.create(
            monitor=self.monitor, timestamp=self.job.cursor - timedelta(hours=1, minutes=-5),
            stage=PM25.Stage.RAW, processor='', value=10.0, location=self.monitor.location,
        )
        with self.captureOnCommitCallbacks(execute=True):
            backfill_summaries_tick()

        # The dispatched backfill_monitor_chunk task ran synchronously (immediate=True)
        # and decremented pending_tasks back to 0, then the tick's own transaction
        # already moved on — check the job ended up in the monitors phase with the
        # batch drained.
        self.job.refresh_from_db()
        assert self.job.phase == SummaryBackfillJob.Phase.MONITORS
        assert self.job.pending_tasks == 0
        assert self.job.batch_id == 1
        assert MonitorSummary.objects.filter(monitor=self.monitor).exists()

    def test_idle_job_with_no_data_dispatches_empty_batch(self):
        with self.captureOnCommitCallbacks(execute=True):
            backfill_summaries_tick()
        self.job.refresh_from_db()
        assert self.job.phase == SummaryBackfillJob.Phase.MONITORS
        assert self.job.pending_tasks == 0
        assert self.job.batch_id == 1


class BackfillSummariesTickDispatchRegionsTests(TestCase):
    fixtures = ['purple-air.yaml', 'regions.yaml']

    def setUp(self):
        from camp.apps.regions.models import Region
        self.region = Region.objects.filter(boundary__isnull=False).first()
        if not self.region:
            self.skipTest('no region with boundary in fixtures')
        monitor = PurpleAir.objects.first()
        monitor.position = self.region.boundary.geometry.centroid
        monitor.save()

        now = timezone.now().replace(minute=0, second=0, microsecond=0)
        self.job = SummaryBackfillJob.objects.create(
            cursor=now, chunk_start=now - timedelta(days=7),
            range_start=now - timedelta(days=30), range_end=now,
            phase=SummaryBackfillJob.Phase.MONITORS, pending_tasks=0, batch_id=1,
        )

    def test_monitors_drained_dispatches_region_batch(self):
        with self.captureOnCommitCallbacks(execute=True):
            backfill_summaries_tick()
        self.job.refresh_from_db()
        assert self.job.phase == SummaryBackfillJob.Phase.REGIONS
        assert self.job.batch_id == 2

    def test_monitors_still_pending_does_nothing(self):
        self.job.pending_tasks = 3
        self.job.phase_started_at = timezone.now()
        self.job.save()
        backfill_summaries_tick()
        self.job.refresh_from_db()
        assert self.job.phase == SummaryBackfillJob.Phase.MONITORS
        assert self.job.pending_tasks == 3
        assert self.job.batch_id == 1


class BackfillSummariesTickCompleteChunkTests(TestCase):
    def setUp(self):
        # Chunk whose chunk_start lands exactly on a month start (Jul 1,
        # 2023), so completing it exercises both the daily and the
        # higher-rollup cascade (July is a quarter-start month) in one call.
        self.month_start = _day(2023, 7, 1)
        self.job = SummaryBackfillJob.objects.create(
            cursor=self.month_start + timedelta(days=2),
            chunk_start=self.month_start,
            range_start=self.month_start - timedelta(days=365),
            range_end=self.month_start + timedelta(days=2),
            phase=SummaryBackfillJob.Phase.REGIONS, pending_tasks=0, batch_id=1,
        )

    def test_regions_drained_advances_cursor_to_chunk_start(self):
        backfill_summaries_tick()
        self.job.refresh_from_db()
        assert self.job.cursor == self.month_start
        assert self.job.phase == SummaryBackfillJob.Phase.IDLE
        assert self.job.chunk_start is None

    def test_regions_drained_resets_failure_count(self):
        self.job.consecutive_failures = 2
        self.job.last_error = 'boom'
        self.job.save()
        backfill_summaries_tick()
        self.job.refresh_from_db()
        assert self.job.consecutive_failures == 0
        assert self.job.last_error == ''

    def test_reaching_range_start_marks_job_done(self):
        self.job.range_start = self.month_start
        self.job.save()
        backfill_summaries_tick()
        self.job.refresh_from_db()
        assert self.job.state == SummaryBackfillJob.State.DONE

    def test_july_first_cascades_monthly_and_quarterly_rollups(self):
        # July is a quarter-start month (Jul/Aug/Sep = Q3) — crossing Jul 1
        # while walking backward should trigger a monthly AND a quarterly
        # rollup call, on top of the daily rollups for each day in the
        # chunk. Rollup *correctness* (the actual aggregated values) is
        # already covered by RollupMonitorSummariesTests /
        # RollupRegionSummariesTests in tests.py — this only proves the
        # cascade invokes the right windows.
        with patch('camp.apps.summaries.tasks.rollup_monitor_summaries') as mock_rollup:
            backfill_summaries_tick()

        resolutions_called = [call.args[0] for call in mock_rollup.call_args_list]
        assert BaseSummary.Resolution.DAILY in resolutions_called
        assert BaseSummary.Resolution.MONTHLY in resolutions_called
        assert BaseSummary.Resolution.QUARTERLY in resolutions_called
        assert BaseSummary.Resolution.SEASONAL not in resolutions_called
        assert BaseSummary.Resolution.YEARLY not in resolutions_called

        monthly_call = next(c for c in mock_rollup.call_args_list if c.args[0] == BaseSummary.Resolution.MONTHLY)
        assert monthly_call.args[2] == self.month_start  # window_start


class BackfillSummariesTickCompleteChunkMonthBoundaryTests(TestCase):
    """
    Regression coverage for a rollup-ordering bug in _backfill_complete_chunk.

    Chunks are fixed 7-day windows that are NOT aligned to month boundaries,
    so a month's 1st very often falls in the *middle* of a chunk rather than
    at its start/end. The buggy implementation interleaved daily rollups and
    higher-rollup cascades in a single pass over the chunk's days (in
    ascending order): when it reached June 1st, the June MONTHLY rollup fired
    immediately — before June 2nd's daily rollup (later in the same loop,
    still to come) had been written — permanently undercounting the month.

    This test uses a chunk spanning May 30 - Jun 3, 2023 (May-tail days plus
    June-head days, with June 1st landing mid-chunk, not at an edge) and
    proves the resulting MONTHLY MonitorSummary reflects data from both
    June 1 and June 2.
    """
    fixtures = ['purple-air.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.first()

        self.chunk_start = _day(2023, 5, 30)
        self.cursor = _day(2023, 6, 3)
        self.june_1 = _day(2023, 6, 1)
        self.june_2 = _day(2023, 6, 2)

        PM25.objects.create(
            monitor=self.monitor, timestamp=self.june_1 + timedelta(hours=12, minutes=5),
            stage=PM25.Stage.RAW, processor='', value=10.0, location=self.monitor.location,
        )
        PM25.objects.create(
            monitor=self.monitor, timestamp=self.june_2 + timedelta(hours=12, minutes=5),
            stage=PM25.Stage.RAW, processor='', value=50.0, location=self.monitor.location,
        )

        # Populate the HOURLY MonitorSummary rows a real backfill would
        # already have written in the MONITORS phase of earlier ticks.
        backfill_monitor_hours(self.monitor, self.chunk_start, self.cursor, [PM25])

        self.job = SummaryBackfillJob.objects.create(
            cursor=self.cursor, chunk_start=self.chunk_start,
            range_start=self.chunk_start - timedelta(days=365), range_end=self.cursor,
            phase=SummaryBackfillJob.Phase.REGIONS, pending_tasks=0, batch_id=1,
        )

    def test_monthly_rollup_includes_all_days_in_chunk_not_just_up_to_month_start(self):
        backfill_summaries_tick()

        monthly = MonitorSummary.objects.get(
            monitor=self.monitor, resolution=BaseSummary.Resolution.MONTHLY,
            entry_type='pm25', processor='', timestamp=self.june_1,
        )
        # Both June 1 (10.0) and June 2 (50.0) must have contributed. Under
        # the old bug, only June 1's daily summary existed by the time the
        # MONTHLY rollup fired, giving count=1 / sum_value=10.0.
        assert monthly.count == 2
        assert monthly.sum_value == 60.0


class BackfillSummariesTickStalenessRecoveryTests(TestCase):
    def setUp(self):
        now = timezone.now().replace(minute=0, second=0, microsecond=0)
        self.job = SummaryBackfillJob.objects.create(
            cursor=now, chunk_start=now - timedelta(days=7),
            range_start=now - timedelta(days=30), range_end=now,
            phase=SummaryBackfillJob.Phase.MONITORS, pending_tasks=5, batch_id=1,
        )

    def test_fresh_batch_is_left_alone(self):
        self.job.phase_started_at = timezone.now()
        self.job.save()
        backfill_summaries_tick()
        self.job.refresh_from_db()
        assert self.job.pending_tasks == 5
        assert self.job.phase == SummaryBackfillJob.Phase.MONITORS

    def test_stale_monitors_batch_redispatches_monitors_only(self):
        self.job.phase_started_at = timezone.now() - timedelta(minutes=61)
        self.job.save()
        backfill_summaries_tick()
        self.job.refresh_from_db()
        # A stall never jumps back to idle — it re-dispatches the same phase
        # that stalled, so an already-completed earlier phase is never redone.
        assert self.job.phase == SummaryBackfillJob.Phase.MONITORS
        assert self.job.batch_id == 2
        assert self.job.consecutive_failures == 1
        assert 'stalled' in self.job.last_error
        assert 'restarting the monitors phase' in self.job.last_error

    def test_five_consecutive_stalls_marks_job_failed(self):
        self.job.phase_started_at = timezone.now() - timedelta(minutes=61)
        self.job.consecutive_failures = 4
        self.job.save()
        backfill_summaries_tick()
        self.job.refresh_from_db()
        assert self.job.state == SummaryBackfillJob.State.FAILED
        assert self.job.phase == SummaryBackfillJob.Phase.IDLE
        assert self.job.pending_tasks == 0


class BackfillSummariesTickRegionsStalenessRecoveryTests(TestCase):
    """
    Regression coverage for the "regions stall discards a completed monitors
    phase too" bug: a regions-phase stall must re-dispatch regions only, not
    fall all the way back through monitors (which already succeeded).
    """
    fixtures = ['purple-air.yaml', 'regions.yaml']

    def setUp(self):
        self.region = Region.objects.filter(boundary__isnull=False).first()
        if not self.region:
            self.skipTest('no region with boundary in fixtures')
        monitor = PurpleAir.objects.first()
        monitor.position = self.region.boundary.geometry.centroid
        monitor.save()

        now = timezone.now().replace(minute=0, second=0, microsecond=0)
        self.job = SummaryBackfillJob.objects.create(
            cursor=now, chunk_start=now - timedelta(days=7),
            range_start=now - timedelta(days=30), range_end=now,
            phase=SummaryBackfillJob.Phase.REGIONS, pending_tasks=3, batch_id=5,
            phase_started_at=timezone.now() - timedelta(minutes=61),
        )

    def test_stale_regions_batch_redispatches_regions_only(self):
        with self.captureOnCommitCallbacks(execute=True):
            backfill_summaries_tick()
        self.job.refresh_from_db()
        assert self.job.phase == SummaryBackfillJob.Phase.REGIONS
        assert self.job.batch_id == 6
        assert self.job.consecutive_failures == 1
        assert 'restarting the regions phase' in self.job.last_error
