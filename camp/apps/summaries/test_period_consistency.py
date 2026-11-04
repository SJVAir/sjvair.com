"""The backfill job, rebuild_summaries and the scheduled tasks must write the same rows."""
from datetime import datetime, timedelta, timezone as dt_timezone
from io import StringIO
from unittest.mock import patch

from django.conf import settings
from django.core.management import call_command
from django.test import TestCase

from camp.apps.entries.models import PM25
from camp.apps.monitors.purpleair.models import PurpleAir
from camp.apps.regions.models import Region
from camp.apps.summaries.models import BaseSummary, MonitorSummary, RegionSummary, SummaryBackfillJob
from camp.apps.summaries.periods import is_period_start, iter_hours, iter_period_starts
from camp.apps.summaries.tasks import (
    _previous_period_start,
    backfill_summaries_tick,
    daily_monitor_summaries,
    daily_region_summaries,
    hourly_monitor_summaries,
    hourly_region_summaries,
)
from camp.utils.datetime import make_aware

LA = settings.DEFAULT_TIMEZONE
R = BaseSummary.Resolution


def _pacific(y, m, d):
    return make_aware(datetime(y, m, d), LA)


def _iso(ts):
    return ts.astimezone(LA).isoformat()


class PeriodConsistencyTests(TestCase):
    fixtures = ['purple-air.yaml', 'regions.yaml']

    def setUp(self):
        self.region = Region.objects.filter(boundary__isnull=False).first()
        self.monitor = PurpleAir.objects.first()
        self.monitor.position = self.region.boundary.geometry.point_on_surface
        self.monitor.save()

    def _seed_entries(self):
        start = _pacific(2026, 10, 25).astimezone(dt_timezone.utc)
        end = _pacific(2026, 11, 5).astimezone(dt_timezone.utc)
        entries = []
        ts = start
        n = 0
        while ts < end:
            entries.append(PM25(
                monitor=self.monitor, timestamp=ts, stage=PM25.Stage.RAW,
                processor='', value=float(5 + n % 17), location=self.monitor.location,
            ))
            ts += timedelta(minutes=30)
            n += 1
        PM25.objects.bulk_create(entries)

    def _wipe(self):
        MonitorSummary.objects.all().delete()
        RegionSummary.objects.all().delete()
        SummaryBackfillJob.objects.all().delete()

    def _day_rows(self):
        rows = {
            ('monitor', r.resolution, r.timestamp, r.count, round(r.mean, 6))
            for r in MonitorSummary.objects.filter(resolution=R.DAILY)
        }
        rows |= {
            ('region', r.resolution, r.timestamp, r.count, round(r.mean, 6))
            for r in RegionSummary.objects.filter(resolution=R.DAILY)
        }
        return rows

    def _via_backfill(self):
        call_command('backfill_summaries', 'start', '--from', '2026-10-26', '--to', '2026-11-04')
        for _ in range(200):
            SummaryBackfillJob.objects.update(locked_at=None)
            with self.captureOnCommitCallbacks(execute=True):
                backfill_summaries_tick()
            if SummaryBackfillJob.objects.get().state != SummaryBackfillJob.State.RUNNING:
                break
        assert SummaryBackfillJob.objects.get().state == SummaryBackfillJob.State.DONE

    def _via_rebuild(self):
        call_command('rebuild_summaries', '2026-10-26', '2026-11-04', '--monitor', str(self.monitor.pk), stdout=StringIO())

    def _via_tasks(self):
        start, end = _pacific(2026, 10, 26), _pacific(2026, 11, 4)
        for hour in iter_hours(start, end):
            hourly_monitor_summaries(hour=hour)
            hourly_region_summaries(hour=hour)
        for day in iter_period_starts('day', start, end):
            daily_monitor_summaries(day=day)
            daily_region_summaries(day=day)

    def test_three_paths_write_the_same_rows(self):
        self._seed_entries()
        results = []
        for build in (self._via_backfill, self._via_rebuild, self._via_tasks):
            self._wipe()
            build()
            results.append(self._day_rows())
        assert results[0], 'no day rows were written'
        assert any(r[0] == 'region' for r in results[0])
        assert results[0] == results[1] == results[2]
        for _, resolution, ts, _, _ in results[0]:
            assert is_period_start(resolution, ts), _iso(ts)

    def test_rebuild_includes_the_repeated_fall_back_hour(self):
        self._seed_entries()
        call_command('rebuild_summaries', '2026-11-01', '2026-11-02', '--region', str(self.region.pk), stdout=StringIO())
        hourly = RegionSummary.objects.filter(region=self.region, resolution=R.HOURLY)
        stamps = {r.timestamp for r in hourly}
        assert datetime(2026, 11, 1, 9, tzinfo=dt_timezone.utc) in stamps
        day_start = _pacific(2026, 11, 1)
        assert hourly.filter(timestamp__gte=day_start, timestamp__lt=_pacific(2026, 11, 2)).count() == 25

    def test_default_periods(self):
        def previous(resolution, now):
            with patch('camp.apps.summaries.tasks.timezone.now', return_value=now):
                return _previous_period_start(resolution)

        march = datetime(2026, 3, 1, 9, 30, tzinfo=dt_timezone.utc)   # 01:30 PST
        assert _iso(previous('month', march)) == '2026-02-01T00:00:00-08:00'
        assert _iso(previous('season', march)) == '2025-12-01T00:00:00-08:00'
        fall = datetime(2026, 11, 1, 9, 10, tzinfo=dt_timezone.utc)
        assert _iso(previous('day', fall)) == '2026-10-31T00:00:00-07:00'
