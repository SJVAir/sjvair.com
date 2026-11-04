"""repair_summaries: delete misaligned period rows, fill missing region hours, re-roll."""
from datetime import datetime, timedelta, timezone as dt_timezone
from io import StringIO
from unittest.mock import patch

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.db import connection, transaction
import pytest

from camp.apps.monitors.purpleair.models import PurpleAir
from camp.apps.regions.models import Region
from camp.apps.summaries import repair
from camp.apps.summaries.aggregators import compute_stats
from camp.apps.summaries.backfill import backfill_region_hours
from camp.apps.summaries.models import BaseSummary, MonitorSummary, RegionSummary
from camp.apps.summaries.periods import is_period_start, iter_hours
from camp.apps.summaries.tasks import rollup_monitor_summaries, rollup_region_summaries
from camp.utils.datetime import make_aware

LA = settings.DEFAULT_TIMEZONE
R = BaseSummary.Resolution
UTC = dt_timezone.utc


def _pacific(y, m, d, h=0):
    return make_aware(datetime(y, m, d, h), LA)


def _iso(ts):
    return ts.astimezone(LA).isoformat()


class RepairSummariesTests(TestCase):
    fixtures = ['purple-air.yaml', 'regions.yaml']

    # Today in Pacific, fixed so which periods count as finished doesn't move.
    NOW = _pacific(2026, 11, 4, 12)

    def setUp(self):
        self.region = Region.objects.filter(boundary__isnull=False).first()
        self.monitor = PurpleAir.objects.first()
        self.monitor.position = self.region.boundary.geometry.point_on_surface
        self.monitor.save()

    # ---- Setup helpers ----

    def _seed_hours(self, start, end):
        hours = list(iter_hours(start, end))
        MonitorSummary.objects.bulk_create([
            MonitorSummary(
                monitor=self.monitor, timestamp=hour, resolution=R.HOURLY,
                entry_type='pm25', processor='', **compute_stats([float(5 + i % 17)], 1),
            )
            for i, hour in enumerate(hours)
        ])
        grades = dict(self.region.monitors.with_grade().values_list('pk', 'grade'))
        backfill_region_hours(self.region, hours, grades)
        return hours

    def _old_rollup(self, target, source, start, end):
        rollup_monitor_summaries(target, source, start, end, monitor_ids=[self.monitor.pk])
        rollup_region_summaries(target, source, start, end, region_ids=[self.region.pk])

    def _seed_spring(self):
        """Hourly rows Feb 1 - Mar 10 2026, then the rows the old backfill and scheduler wrote."""
        self._seed_hours(_pacific(2026, 2, 1), _pacific(2026, 3, 10))

        # The old backfill stepped back from a PDT midnight in 24-hour steps, so
        # every standard-time period started at 23:00 the day before.
        anchor = datetime(2026, 3, 1, 7, tzinfo=UTC)
        assert _iso(anchor) == '2026-02-28T23:00:00-08:00'
        for n in range(29):
            day = anchor - timedelta(days=n)
            self._old_rollup(R.DAILY, R.HOURLY, day, day + timedelta(days=1))
        self._old_rollup(R.MONTHLY, R.DAILY, anchor - timedelta(days=28), anchor)
        self._old_rollup(R.MONTHLY, R.DAILY, anchor, anchor + timedelta(days=31))
        self._old_rollup(R.SEASONAL, R.MONTHLY, anchor, anchor + timedelta(days=92))

        # The old scheduler's May-July season.
        may = _pacific(2026, 5, 1)
        MonitorSummary.objects.create(
            monitor=self.monitor, timestamp=may, resolution=R.SEASONAL,
            entry_type='pm25', processor='', **compute_stats([10.0], 1),
        )
        stats = compute_stats([10.0], 1)
        stats.pop('is_complete')
        RegionSummary.objects.create(
            region=self.region, timestamp=may, resolution=R.SEASONAL,
            entry_type='pm25', station_count=1, weight=1.0, **stats,
        )

        # Finding 3: the region's hours for one day were never written.
        RegionSummary.objects.filter(
            region=self.region, resolution=R.HOURLY,
            timestamp__gte=_pacific(2026, 3, 5), timestamp__lt=_pacific(2026, 3, 6),
        ).delete()

    def _repair(self, *args, start='2026-02-01', end='2026-06-01', now=None):
        out = StringIO()
        with patch('django.utils.timezone.now', return_value=now or self.NOW):
            call_command(
                'repair_summaries', start, end,
                '--monitor', str(self.monitor.pk), '--region', str(self.region.pk),
                *args, stdout=out,
            )
        return out.getvalue()

    def _snapshot(self, resolutions=None):
        def rows(qs, kind, key):
            if resolutions:
                qs = qs.filter(resolution__in=resolutions)
            return {
                (kind, r.resolution, r.timestamp): (r.count, round(r.mean, 6), r.minimum, r.maximum)
                for r in qs.filter(**{key: getattr(self, kind).pk})
            }
        return {
            **rows(MonitorSummary.objects.all(), 'monitor', 'monitor_id'),
            **rows(RegionSummary.objects.all(), 'region', 'region_id'),
        }

    def _non_hourly(self):
        return [
            *MonitorSummary.objects.exclude(resolution=R.HOURLY),
            *RegionSummary.objects.exclude(resolution=R.HOURLY),
        ]

    # ---- Tests ----

    def test_dry_run_reports_and_writes_nothing(self):
        self._seed_spring()
        before = self._snapshot()

        output = self._repair('--region-hours', '--dry-run')

        assert self._snapshot() == before
        assert 'region hour: 24 missing hours in 1 region' in output
        for kind in ('monitor', 'region'):
            assert f'{kind} day: 29 misaligned to delete' in output
            assert f'{kind} month: 2 misaligned to delete' in output
            assert f'{kind} season: 2 misaligned to delete' in output
            assert f'{kind} quarter: 0 misaligned to delete' in output
        assert 'Dry run' in output

    def test_repairs_misaligned_rows_and_missing_hours(self):
        self._seed_spring()
        output = self._repair('--region-hours')

        for row in self._non_hourly():
            assert is_period_start(row.resolution, row.timestamp), (row.resolution, _iso(row.timestamp))

        hour_early = datetime(2026, 3, 1, 7, tzinfo=UTC)
        for model in (MonitorSummary, RegionSummary):
            assert not model.objects.filter(timestamp=hour_early).exclude(resolution=R.HOURLY).exists()
            assert not model.objects.filter(resolution=R.SEASONAL, timestamp=_pacific(2026, 5, 1)).exists()

        region_hours = RegionSummary.objects.filter(
            region=self.region, resolution=R.HOURLY,
            timestamp__gte=_pacific(2026, 3, 5), timestamp__lt=_pacific(2026, 3, 6),
        )
        assert region_hours.count() == 24

        # Pacific facts: one row per hour, so a day's count is its length in hours.
        days = {
            _iso(r.timestamp): r.count
            for r in MonitorSummary.objects.filter(monitor=self.monitor, resolution=R.DAILY)
        }
        assert days['2026-02-01T00:00:00-08:00'] == 24
        assert days['2026-03-08T00:00:00-08:00'] == 23   # spring forward
        assert days['2026-03-09T00:00:00-07:00'] == 24
        assert len(days) == 37                           # Feb 1 - Mar 9
        feb = MonitorSummary.objects.get(monitor=self.monitor, resolution=R.MONTHLY, timestamp=_pacific(2026, 2, 1))
        assert feb.count == 28 * 24
        march = MonitorSummary.objects.get(monitor=self.monitor, resolution=R.MONTHLY, timestamp=_pacific(2026, 3, 1))
        assert march.count == 9 * 24 - 1

        assert 'monitor day: 29 misaligned deleted' in output
        assert 'region hour: 24 missing hours in 1 region' in output

        repaired = self._snapshot([R.DAILY, R.MONTHLY])

        # A clean rebuild of the same scope writes the same day and month rows.
        MonitorSummary.objects.exclude(resolution=R.HOURLY).delete()
        RegionSummary.objects.all().delete()
        call_command('rebuild_summaries', '2026-02-01', '2026-06-01', '--region', str(self.region.pk), stdout=StringIO())
        rebuilt = self._snapshot([R.DAILY, R.MONTHLY])
        assert repaired
        assert repaired == rebuilt

    def test_unfinished_periods_are_not_written(self):
        self._seed_spring()
        self._repair('--region-hours', now=_pacific(2026, 3, 10))

        for model in (MonitorSummary, RegionSummary):
            assert not model.objects.filter(resolution=R.MONTHLY, timestamp=_pacific(2026, 3, 1)).exists()
            assert not model.objects.filter(resolution=R.SEASONAL, timestamp=_pacific(2026, 3, 1)).exists()
            # The finished ones are.
            assert model.objects.filter(resolution=R.MONTHLY, timestamp=_pacific(2026, 2, 1)).exists()
            assert model.objects.filter(resolution=R.SEASONAL, timestamp=_pacific(2025, 12, 1)).exists()
        for row in self._non_hourly():
            assert is_period_start(row.resolution, row.timestamp), (row.resolution, _iso(row.timestamp))

    def test_second_run_finds_nothing_and_keeps_values(self):
        self._seed_spring()
        self._repair('--region-hours')
        first = self._snapshot()

        output = self._repair('--region-hours')

        assert 'region hour: 0 missing hours' in output
        for kind in ('monitor', 'region'):
            for resolution in ('day', 'month', 'quarter', 'season', 'year'):
                assert f'{kind} {resolution}: 0 misaligned deleted' in output
        assert self._snapshot() == first

    def test_a_range_inside_a_month_repairs_the_whole_month(self):
        # Re-rolling February reads every February day row, so a range that
        # starts mid-month must not leave the month's earlier misaligned days
        # in place (they would shift or double-count hours in the month row).
        self._seed_spring()
        self._repair(start='2026-02-15', end='2026-03-11')

        feb = MonitorSummary.objects.get(monitor=self.monitor, resolution=R.MONTHLY, timestamp=_pacific(2026, 2, 1))
        assert feb.count == 28 * 24
        days = MonitorSummary.objects.filter(
            monitor=self.monitor, resolution=R.DAILY,
            timestamp__gte=_pacific(2026, 2, 1), timestamp__lt=_pacific(2026, 3, 1),
        )
        assert days.count() == 28
        assert sum(d.count for d in days) == 28 * 24
        for row in self._non_hourly():
            assert is_period_start(row.resolution, row.timestamp), (row.resolution, _iso(row.timestamp))

    def test_fall_back_day(self):
        self._seed_hours(_pacific(2026, 10, 25), _pacific(2026, 11, 4))
        # Stepping back from a PST midnight puts daylight-time days at 01:00.
        anchor = datetime(2026, 11, 4, 8, tzinfo=UTC)
        assert _iso(anchor) == '2026-11-04T00:00:00-08:00'
        for n in range(1, 11):
            day = anchor - timedelta(days=n)
            self._old_rollup(R.DAILY, R.HOURLY, day, day + timedelta(days=1))
        assert MonitorSummary.objects.filter(timestamp=datetime(2026, 11, 1, 8, tzinfo=UTC)).exists()

        output = self._repair(start='2026-10-26', end='2026-11-04', now=_pacific(2026, 11, 5))

        assert 'monitor day: 8 misaligned deleted' in output
        for row in self._non_hourly():
            assert is_period_start(row.resolution, row.timestamp), (row.resolution, _iso(row.timestamp))
        days = {
            _iso(r.timestamp): r.count
            for r in MonitorSummary.objects.filter(monitor=self.monitor, resolution=R.DAILY)
        }
        assert days['2026-10-31T00:00:00-07:00'] == 24
        assert days['2026-11-01T00:00:00-07:00'] == 25   # fall back
        assert days['2026-11-02T00:00:00-08:00'] == 24
        october = MonitorSummary.objects.get(monitor=self.monitor, resolution=R.MONTHLY, timestamp=_pacific(2026, 10, 1))
        assert october.count == 7 * 24

    def test_delete_is_one_statement_per_resolution(self):
        self._seed_spring()
        with patch('django.utils.timezone.now', return_value=self.NOW):
            with CaptureQueriesContext(connection) as ctx:
                call_command(
                    'repair_summaries', '2026-02-01', '2026-06-01',
                    '--monitor', str(self.monitor.pk), stdout=StringIO(),
                )
        deletes = [q['sql'] for q in ctx.captured_queries if q['sql'].startswith('DELETE')]
        # day, month and season each have misaligned monitor rows.
        assert len(deletes) == 3
        assert all('summaries_monitorsummary' in sql for sql in deletes)

    def test_rows_standing_for_periods_after_the_run_are_left_and_reported(self):
        # A Dec 1-15 2025 run widens day/month work to 2025-01-01 -> 2026-03-01
        # (year 2025 and the Dec-Feb season are finished). The rows stamped
        # 2026-02-28T23:00-08:00 stand for March 1 periods, which this run
        # doesn't re-roll, so it must leave them and say so.
        self._seed_spring()
        hour_early = datetime(2026, 3, 1, 7, tzinfo=UTC)

        output = self._repair(start='2025-12-01', end='2025-12-15')

        for model in (MonitorSummary, RegionSummary):
            for resolution in (R.DAILY, R.MONTHLY, R.SEASONAL):
                assert model.objects.filter(resolution=resolution, timestamp=hour_early).exists(), (model, resolution)
            # The May 1 season stands for Mar-May too, and is past the scan.
            assert model.objects.filter(resolution=R.SEASONAL, timestamp=_pacific(2026, 5, 1)).exists()
            # February's window holds the Feb 28 23:00 day row, so February (and
            # the Dec-Feb season above it) is skipped: the Jan 31 23:00 month
            # row standing for February stays too, and no February row is written.
            assert model.objects.filter(resolution=R.MONTHLY, timestamp=datetime(2026, 2, 1, 7, tzinfo=UTC)).exists()
            assert not model.objects.filter(resolution=R.MONTHLY, timestamp=_pacific(2026, 2, 1)).exists()
            assert not model.objects.filter(resolution=R.SEASONAL, timestamp=_pacific(2025, 12, 1)).exists()
            # Days are independent of each other: the rest are repaired.
            assert not model.objects.filter(resolution=R.DAILY, timestamp=datetime(2026, 2, 1, 7, tzinfo=UTC)).exists()
            assert model.objects.filter(resolution=R.DAILY, timestamp=_pacific(2026, 2, 28)).exists()
        for kind in ('monitor', 'region'):
            assert f'{kind} day: 28 misaligned deleted, 1 left in place (period outside this run), 0 left in place (period skipped)' in output
            assert f'{kind} month: 0 misaligned deleted, 1 left in place (period outside this run), 1 left in place (period skipped)' in output
            assert f'{kind} season: 0 misaligned deleted, 1 left in place (period outside this run), 0 left in place (period skipped)' in output
            assert (
                f'left in place: {kind} month at 2026-02-28T23:00:00-08:00 stands for the period '
                'starting 2026-03-01T00:00:00-08:00, outside this run; widen the range to repair it'
            ) in output
            assert (
                f'left in place: {kind} month at 2026-01-31T23:00:00-08:00 stands for the period '
                'starting 2026-02-01T00:00:00-08:00, which this run skips (see skipped)'
            ) in output
            assert (
                f'skipped: {kind} month starting 2026-02-01T00:00:00-08:00 is not deleted or re-rolled: '
                'its window holds the day row at 2026-02-28T23:00:00-08:00, left in place'
            ) in output
            assert (
                f'skipped: {kind} season starting 2025-12-01T00:00:00-08:00 is not deleted or re-rolled: '
                'its window holds the month row at 2026-02-28T23:00:00-08:00, left in place'
            ) in output
            assert "outside this run's range" not in output
        assert '  day: deletes misaligned rows standing for the 424 periods 2025-01-01T00:00:00-08:00 -> 2026-03-01T00:00:00-08:00' in output
        assert '  season: deletes misaligned rows standing for the 1 period 2025-12-01T00:00:00-08:00 -> 2026-03-01T00:00:00-08:00' in output

        # Widening the range to cover March repairs everything.
        self._repair(start='2025-12-01', end='2026-06-01')
        for row in self._non_hourly():
            assert is_period_start(row.resolution, row.timestamp), (row.resolution, _iso(row.timestamp))
        feb = MonitorSummary.objects.get(monitor=self.monitor, resolution=R.MONTHLY, timestamp=_pacific(2026, 2, 1))
        assert feb.count == 28 * 24

    def test_a_skip_records_its_cause(self):
        # A Dec 1-15 2025 run covers days through Feb 2026, so the day row
        # stamped Feb 28 23:00 (standing for Mar 1) is left in place. February's
        # window holds that row; the Dec-Feb season above it holds no misaligned
        # month row, only the skipped February.
        hour_early = datetime(2026, 3, 1, 7, tzinfo=UTC)
        spans = repair.plan(_pacific(2025, 12, 1), _pacific(2025, 12, 15), self.NOW)
        decision = repair.decide(spans, {R.DAILY: [hour_early]})
        assert decision.skipped == {R.MONTHLY: [_pacific(2026, 2, 1)], R.SEASONAL: [_pacific(2025, 12, 1)]}
        assert decision.causes == {
            R.MONTHLY: {_pacific(2026, 2, 1): ('row', R.DAILY, hour_early)},
            R.SEASONAL: {_pacific(2025, 12, 1): ('period', R.MONTHLY, _pacific(2026, 2, 1))},
        }

    def test_each_resolution_is_deleted_then_rerolled_before_the_next(self):
        # Deleting every misaligned row up front leaves standard-time months and
        # seasons missing for the whole re-roll. Each resolution is instead
        # deleted and re-rolled before the next, so when months re-roll the
        # days below them are already clean, and when days re-roll the old
        # month rows are still there.
        self._seed_spring()
        hour_early = datetime(2026, 3, 1, 7, tzinfo=UTC)
        seen = []
        real = rollup_monitor_summaries

        def spy(target, source, start, end, **kwargs):
            rows = MonitorSummary.objects.filter(monitor=self.monitor)
            seen.append((
                target,
                rows.filter(resolution=R.MONTHLY, timestamp=hour_early).exists(),
                [r.timestamp for r in rows.filter(resolution=R.DAILY, timestamp__gte=start - timedelta(days=1), timestamp__lt=end)],
            ))
            return real(target, source, start, end, **kwargs)

        with patch.dict(repair.KINDS, {'monitor': (MonitorSummary, 'monitor_id', spy)}):
            output = self._repair()

        first_day = next(s for s in seen if s[0] == R.DAILY)
        assert first_day[1], 'misaligned month rows are deleted only right before months re-roll'
        months = [s for s in seen if s[0] == R.MONTHLY]
        assert months
        for _, old_month_left, days in months:
            assert not old_month_left
            assert all(is_period_start(R.DAILY, ts) for ts in days), [_iso(ts) for ts in days]
        feb = next(s for s in months if s[2] and min(s[2]) == _pacific(2026, 2, 1))
        assert len(feb[2]) == 28

        lines = output.splitlines()

        def at(prefix, text):
            return next(i for i, line in enumerate(lines) if line.startswith(prefix) and text in line)
        for kind in ('monitor', 'region'):
            order = []
            for resolution in repair.RESOLUTIONS:
                order += [at(f'{kind} {resolution}: ', 'misaligned deleted'), at(f'{kind} {resolution}: ', 'windows rolled')]
            assert order == sorted(order), output
        assert 'monitor day: 29 misaligned deleted' in output

    def test_result_matches_deleting_everything_first(self):
        # The same rows as the old order (every delete, then every re-roll).
        self._seed_spring()
        with transaction.atomic():
            spans = repair.plan(_pacific(2026, 2, 1), _pacific(2026, 6, 1), self.NOW)
            scan_start, scan_end = repair.scan_range(spans)
            decisions = {}
            for kind, ids in (('monitor', [self.monitor.pk]), ('region', [self.region.pk])):
                model, ids_field, _ = repair.KINDS[kind]
                decisions[kind] = repair.decide(spans, repair.find_misaligned(model, ids_field, ids, scan_start, scan_end))
                repair.delete_misaligned(kind, ids, decisions[kind].delete)
            for kind, ids in (('monitor', [self.monitor.pk]), ('region', [self.region.pk])):
                repair.reroll(kind, ids, None, None, None, windows=decisions[kind].windows)
            expected = self._snapshot()
            transaction.set_rollback(True)

        self._repair()
        assert len(expected) > 1000
        assert self._snapshot() == expected

    def test_reroll_with_no_windows_rolls_nothing(self):
        self._seed_spring()
        before = self._snapshot()
        counts = repair.reroll('monitor', [self.monitor.pk], _pacific(2026, 2, 1), _pacific(2026, 6, 1), self.NOW, windows={})
        assert counts == {resolution: 0 for resolution in repair.RESOLUTIONS}
        assert self._snapshot() == before

    def test_header_states_the_region_hour_span_and_counts_in_words(self):
        self._seed_spring()
        output = self._repair('--region-hours', '--dry-run', start='2026-02-15', end='2026-03-11')
        header = output.split('Dry run: nothing will be written.')[0]
        assert (
            'Region hours: fills missing hourly region rows 2026-02-15T00:00:00-08:00 -> '
            '2026-03-11T00:00:00-07:00 only; day and month re-rolls outside it read the region hours already there'
        ) in header
        assert ' 1 periods' not in output
        assert '  quarter: deletes misaligned rows standing for the 1 period ' in header
        assert 'region hour: 24 missing hours in 1 region' in output
        assert 'region(s)' not in output
        assert '1 windows' not in output

    def test_region_hours_help_states_its_span(self):
        from camp.apps.summaries.management.commands.repair_summaries import Command
        parser = Command().create_parser('manage.py', 'repair_summaries')
        assert 'only [start, end)' in ' '.join(parser.format_help().split())

    def test_missing_region_hours_filters_by_monitor_for_a_small_scope(self):
        self._seed_spring()
        # A monitor outside the region with a row in an hour the region already has.
        other_monitor = PurpleAir.objects.create(name='Elsewhere', position='POINT(0 0)', sensor_id=11235)
        assert not self.region.monitors.filter(pk=other_monitor.pk).exists()
        MonitorSummary.objects.create(
            monitor=other_monitor, timestamp=_pacific(2026, 3, 2, 3), resolution=R.HOURLY,
            entry_type='pm25', processor='', **compute_stats([10.0], 1),
        )
        start, end = _pacific(2026, 3, 1), _pacific(2026, 3, 8)

        def run():
            with CaptureQueriesContext(connection) as ctx:
                missing = repair.missing_region_hours([self.region.pk], start, end)
            hourly = [q['sql'] for q in ctx.captured_queries if 'summaries_monitorsummary' in q['sql']]
            return missing, hourly

        small, small_sql = run()
        assert len(small_sql) == 1
        assert '"monitor_id" IN' in small_sql[0]

        with patch.object(repair, 'REGION_HOUR_MONITOR_FILTER_MAX', 0):
            wide, wide_sql = run()
        assert len(wide_sql) == 1
        assert '"monitor_id" IN' not in wide_sql[0]

        assert small == wide
        assert len(small[self.region.pk]) == 24

    def test_delete_batches_timestamps_and_reports_progress(self):
        self._seed_spring()
        with patch.object(repair, 'DELETE_TIMESTAMP_BATCH', 10):
            with patch('django.utils.timezone.now', return_value=self.NOW):
                out = StringIO()
                with CaptureQueriesContext(connection) as ctx:
                    call_command(
                        'repair_summaries', '2026-02-01', '2026-06-01',
                        '--monitor', str(self.monitor.pk), stdout=out,
                    )
        deletes = [q['sql'] for q in ctx.captured_queries if q['sql'].startswith('DELETE')]
        assert len(deletes) == 3 + 1 + 1   # 29 days in batches of 10, one month batch, one season batch
        output = out.getvalue()
        assert 'monitor day delete: batch 1/3 (10 rows)' in output
        assert 'monitor day delete: batch 3/3 (9 rows)' in output
        assert 'monitor day roll: 50/' in output

    def test_missing_region_hours_reads_hours_by_week_for_all_regions(self):
        self._seed_spring()
        other = Region.objects.filter(boundary__isnull=False).exclude(pk=self.region.pk).first()
        start, end = _pacific(2026, 2, 1), _pacific(2026, 3, 11)   # 38 days: 6 weeks
        with CaptureQueriesContext(connection) as ctx:
            missing = repair.missing_region_hours([self.region.pk, other.pk], start, end)
        # regions, one monitor lookup per region, then 2 per week.
        assert len(ctx.captured_queries) == 1 + 2 + 2 * 6
        hours = missing[self.region.pk]
        assert len(hours) == 24
        assert _iso(hours[0]) == '2026-03-05T00:00:00-08:00'

    def test_region_flags_leave_monitor_rows_alone(self):
        self._seed_spring()
        monitor_rows = self._snapshot()
        monitor_rows = {k: v for k, v in monitor_rows.items() if k[0] == 'monitor'}
        out = StringIO()
        with patch('django.utils.timezone.now', return_value=self.NOW):
            call_command('repair_summaries', '2026-02-01', '2026-06-01', '--region', str(self.region.pk), stdout=out)
        after = {k: v for k, v in self._snapshot().items() if k[0] == 'monitor'}
        assert after == monitor_rows

    def test_requires_a_scope(self):
        with CaptureQueriesContext(connection) as ctx:
            with pytest.raises(CommandError):
                call_command('repair_summaries', '2026-02-01', '2026-03-01', stdout=StringIO())
        assert len(ctx.captured_queries) == 0

    def test_unknown_region(self):
        with pytest.raises(CommandError, match='999999'):
            call_command('repair_summaries', '2026-02-01', '2026-03-01', '--region', '999999', stdout=StringIO())

    def test_unknown_monitor(self):
        with pytest.raises(CommandError, match='nope'):
            call_command('repair_summaries', '2026-02-01', '2026-03-01', '--monitor', 'nope', stdout=StringIO())

    def test_unknown_types(self):
        with pytest.raises(CommandError, match='toaster'):
            call_command('repair_summaries', '2026-02-01', '2026-03-01', '--monitor-type', 'toaster', stdout=StringIO())
        with pytest.raises(CommandError, match='planet'):
            call_command('repair_summaries', '2026-02-01', '2026-03-01', '--region-type', 'planet', stdout=StringIO())

    def test_region_hours_needs_region_scope(self):
        with pytest.raises(CommandError, match='--region-hours'):
            call_command(
                'repair_summaries', '2026-02-01', '2026-03-01',
                '--monitor', str(self.monitor.pk), '--region-hours', stdout=StringIO(),
            )

    def test_type_flags_scope_by_type(self):
        self._seed_spring()
        out = StringIO()
        with patch('django.utils.timezone.now', return_value=self.NOW):
            call_command(
                'repair_summaries', '2026-02-01', '2026-06-01',
                '--monitor-type', 'purpleair', '--region-type', self.region.type, '--dry-run', stdout=out,
            )
        assert 'monitor day: 29 misaligned to delete' in out.getvalue()
        assert 'region day: 29 misaligned to delete' in out.getvalue()


class FindMisalignedTests(TestCase):
    fixtures = ['purple-air.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.first()
        for ts, resolution in [
            (_pacific(2026, 3, 1), R.DAILY),                  # aligned
            (datetime(2026, 3, 1, 7, tzinfo=UTC), R.DAILY),   # 23:00 the day before
            (_pacific(2026, 5, 1), R.SEASONAL),               # not Dec/Mar/Jun/Sep
            (_pacific(2026, 3, 1), R.SEASONAL),               # aligned
            (datetime(2026, 3, 1, 7, tzinfo=UTC), R.HOURLY),  # hours are never misaligned
        ]:
            MonitorSummary.objects.create(
                monitor=self.monitor, timestamp=ts, resolution=resolution,
                entry_type='pm25', processor='', **compute_stats([10.0], 1),
            )

    def test_finds_rows_that_are_not_period_starts(self):
        found = repair.find_misaligned(MonitorSummary, 'monitor_id', [self.monitor.pk], _pacific(2026, 3, 1), _pacific(2026, 6, 1))
        assert {k: [_iso(t) for t in v] for k, v in found.items()} == {
            'day': ['2026-02-28T23:00:00-08:00'],
            'season': ['2026-05-01T00:00:00-07:00'],
        }

    def test_none_is_every_row_and_empty_is_none(self):
        start, end = _pacific(2026, 3, 1), _pacific(2026, 6, 1)
        assert set(repair.find_misaligned(MonitorSummary, 'monitor_id', None, start, end)) == {'day', 'season'}
        assert repair.find_misaligned(MonitorSummary, 'monitor_id', [], start, end) == {}
