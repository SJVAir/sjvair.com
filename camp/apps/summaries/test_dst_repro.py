"""Reproduces finding 2 (standard-time period starts stamped an hour early)."""
from datetime import datetime, timedelta, timezone as dt_timezone

from django.conf import settings
from django.core.management import call_command
from django.test import TestCase

from camp.apps.monitors.purpleair.models import PurpleAir
from camp.apps.summaries.aggregators import compute_stats
from camp.apps.summaries.backfill import hour_range
from camp.apps.summaries.models import BaseSummary, MonitorSummary, SummaryBackfillJob
from camp.apps.summaries.tasks import backfill_summaries_tick
from camp.utils.datetime import make_aware

LA = settings.DEFAULT_TIMEZONE
R = BaseSummary.Resolution


def _pacific(y, m, d):
    return make_aware(datetime(y, m, d), LA)


class BackfillDstReproTests(TestCase):
    fixtures = ['purple-air.yaml']

    def test_backfill_from_a_summer_time_end_stamps_standard_time_periods(self):
        monitor = PurpleAir.objects.first()
        start, end = _pacific(2026, 2, 1), _pacific(2026, 3, 10)
        MonitorSummary.objects.bulk_create([
            MonitorSummary(
                monitor=monitor, timestamp=hour, resolution=R.HOURLY,
                entry_type='pm25', processor='', **compute_stats([10.0], 1),
            )
            for hour in hour_range(start.astimezone(dt_timezone.utc), end)
        ])

        call_command('backfill_summaries', 'start', '--from', '2026-02-27', '--to', '2026-03-10')
        for _ in range(200):
            SummaryBackfillJob.objects.update(locked_at=None)
            with self.captureOnCommitCallbacks(execute=True):
                backfill_summaries_tick()
            if SummaryBackfillJob.objects.get().state != SummaryBackfillJob.State.RUNNING:
                break

        rows = MonitorSummary.objects.exclude(resolution=R.HOURLY).order_by('resolution', 'timestamp')
        stamps = {(r.resolution, r.timestamp.astimezone(LA).isoformat()) for r in rows}
        print(sorted(stamps))

        assert (R.MONTHLY, '2026-03-01T00:00:00-08:00') in stamps
        assert (R.SEASONAL, '2026-03-01T00:00:00-08:00') in stamps
        assert all(r.timestamp.astimezone(LA).hour == 0 for r in rows)


from unittest.mock import patch

from camp.apps.regions.models import Region
from camp.apps.summaries.models import RegionSummary
from camp.apps.summaries.tasks import hourly_region_summaries


class LateRegionFanOutReproTests(TestCase):
    """Finding 3: the region job picks its hour when it runs, not when it was scheduled."""
    fixtures = ['purple-air.yaml', 'regions.yaml']

    def setUp(self):
        self.region = Region.objects.filter(boundary__isnull=False).first()
        self.monitor = PurpleAir.objects.first()
        self.monitor.position = self.region.boundary.geometry.point_on_surface
        self.monitor.save()
        self.hour = datetime(2026, 11, 2, 9, tzinfo=dt_timezone.utc)
        MonitorSummary.objects.create(
            monitor=self.monitor, timestamp=self.hour, resolution=R.HOURLY,
            entry_type='pm25', processor='', **compute_stats([10.0], 1),
        )

    def _run_at(self, now):
        with patch('camp.apps.summaries.tasks.timezone.now', return_value=now):
            hourly_region_summaries()
        return RegionSummary.objects.filter(region=self.region, resolution=R.HOURLY)

    def test_on_time_run_summarizes_the_hour(self):
        rows = self._run_at(datetime(2026, 11, 2, 10, 50, tzinfo=dt_timezone.utc))
        assert [r.timestamp for r in rows] == [self.hour]

    def test_run_that_starts_after_the_top_of_the_hour_summarizes_nothing(self):
        rows = self._run_at(datetime(2026, 11, 2, 11, 1, tzinfo=dt_timezone.utc))
        assert list(rows) == []   # hour 09:00 is skipped for good; 10:00 has no monitor rows yet
