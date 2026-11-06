from datetime import datetime, timedelta

import tqdm

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.utils.dateparse import parse_date

from django.conf import settings
from django.db.models import Q

from camp.utils.datetime import make_aware
from camp.apps.entries.stages import Stage
from camp.apps.summaries.backfill import backfill_monitor_hours, backfill_region_hours
from camp.apps.summaries.periods import iter_hours, iter_period_starts, period_end
from camp.apps.summaries.models import BaseSummary, MonitorSummary, RegionSummary
from camp.apps.summaries.selection import (
    is_summarized,
    monitor_summary_entry_models,
    region_summary_entry_models,
)
from camp.apps.summaries.tasks import (
    rollup_monitor_summaries,
    rollup_region_summaries,
)


def finished_period_starts(resolution, start, end, now):
    '''
    Starts of the `resolution` periods overlapping [start, end) that have
    ended by `now`. An unfinished period (today, this month, ...) is left for
    its scheduled rollup, as repair does: a row written now would hold a
    partial period, and nothing updates month-and-longer rows before the
    period ends.
    '''
    return [
        ws for ws in iter_period_starts(resolution, start, end)
        if period_end(resolution, ws) <= now
    ]


class Command(BaseCommand):
    help = 'Backfill or recalculate summaries for a date range.'

    def add_arguments(self, parser):
        parser.add_argument('start', help='Start date (YYYY-MM-DD)')
        parser.add_argument('end', nargs='?', default=None, help='End date (YYYY-MM-DD, defaults to now)')
        parser.add_argument('--monitor', dest='monitor_id', metavar='ID',
            help='Recalculate a specific monitor and cascade to its regions')
        parser.add_argument('--region', dest='region_id', metavar='ID',
            help='Recalculate all monitors in a region and the region itself')
        group = parser.add_mutually_exclusive_group()
        group.add_argument('--monitors-only', action='store_true',
            help='Skip region summaries')
        group.add_argument('--regions-only', action='store_true',
            help='Skip monitor summaries')
        parser.add_argument('--async', action='store_true', dest='enqueue',
            help='Enqueue tasks for background processing instead of running synchronously')

    def handle(self, *args, **options):
        from camp.apps.monitors.models import Monitor
        from camp.apps.regions.models import Region

        now = timezone.now()
        start = self._parse_date(options['start'])
        end = (
            self._parse_date(options['end'])
            if options['end']
            else now.replace(minute=0, second=0, microsecond=0)
        )

        if start >= end:
            raise CommandError('start must be before end')

        enqueue = options['enqueue']
        monitors_only = options['monitors_only']
        regions_only = options['regions_only']
        monitor_id = options.get('monitor_id')
        region_id = options.get('region_id')

        # Determine monitor scope
        if monitor_id:
            monitors = Monitor.objects.filter(pk=monitor_id)
            if not monitors.exists():
                raise CommandError(f'Monitor not found: {monitor_id}')
        elif region_id:
            region = Region.all_objects.filter(pk=region_id).first()
            if not region:
                raise CommandError(f'Region not found: {region_id}')
            if not region.boundary:
                raise CommandError(f'Region {region_id} has no boundary geometry')
            monitors = region.monitors
        else:
            monitors = Monitor.objects.all()

        monitor_ids = list(monitors.values_list('pk', flat=True))

        # Determine region scope
        if region_id:
            regions = Region.all_objects.filter(pk=region_id)
        elif monitor_id:
            monitor = monitors.first()
            regions = monitor.regions if monitor else Region.objects.none()
        else:
            regions = Region.objects.all()

        region_ids = list(regions.values_list('pk', flat=True))

        hours = list(iter_hours(start, end))

        self.stdout.write(
            f'Date range: {start:%Y-%m-%d %H:%M} → {end:%Y-%m-%d %H:%M} '
            f'({len(hours):,} hours)'
        )
        self.stdout.write(f'Monitors: {len(monitor_ids):,} | Regions: {len(region_ids):,}')
        self.stdout.flush()

        # Monitor summaries
        if not regions_only:
            if enqueue:
                self._enqueue_monitor_summaries(monitors, hours)
                self._enqueue_monitor_rollups(start, end, now)
            else:
                self._backfill_monitor_summaries(monitors, start, end)
                self._rollup(rollup_monitor_summaries, 'monitor', monitor_ids, start, end, now)

        # Region summaries
        if not monitors_only:
            if enqueue:
                self._enqueue_region_summaries(region_ids, hours, region_summary_entry_models())
                self._enqueue_region_rollups(start, end, now)
            else:
                self._backfill_region_summaries(list(regions), hours)
                self._rollup(rollup_region_summaries, 'region', region_ids, start, end, now)

        self.stdout.write(self.style.SUCCESS('Done.'))

    def _backfill_monitor_summaries(self, monitors, start, end):
        self.stdout.write(f'\nComputing hourly monitor summaries...')
        self.stdout.flush()
        for monitor in tqdm.tqdm(monitors, file=self.stdout, dynamic_ncols=True):
            backfill_monitor_hours(monitor, start, end, monitor_summary_entry_models(monitor))

    def _backfill_region_summaries(self, regions, hours):
        region_monitor_grades = {}
        for region in regions:
            if region.boundary:
                region_monitor_grades[region.pk] = dict(
                    region.monitors.with_grade().values_list('pk', 'grade')
                )

        self.stdout.write(f'\nComputing hourly region summaries...')
        self.stdout.flush()

        for region in tqdm.tqdm(regions, file=self.stdout, dynamic_ncols=True):
            monitor_grades = region_monitor_grades.get(region.pk)
            if not monitor_grades:
                continue
            backfill_region_hours(region, hours, monitor_grades)

    def _rollup(self, rollup_fn, label, ids, start, end, now):
        R = BaseSummary.Resolution
        levels = [
            ('daily',     R.DAILY,     R.HOURLY,  finished_period_starts('day', start, end, now)),
            ('monthly',   R.MONTHLY,   R.DAILY,   finished_period_starts('month', start, end, now)),
            ('quarterly', R.QUARTERLY, R.MONTHLY, finished_period_starts('quarter', start, end, now)),
            ('seasonal',  R.SEASONAL,  R.MONTHLY, finished_period_starts('season', start, end, now)),
            ('yearly',    R.YEARLY,    R.MONTHLY, finished_period_starts('year', start, end, now)),
        ]
        for name, target, source, windows in levels:
            if not windows:
                continue
            self.stdout.write(f'\nRolling up {name} {label} summaries ({len(windows):,} windows)...')
            self.stdout.flush()
            for window_start in tqdm.tqdm(windows, file=self.stdout, dynamic_ncols=True):
                window_end = period_end(target, window_start)
                rollup_fn(target, source, window_start, window_end, **{f'{label}_ids': ids})

    # ---- Async enqueue methods ----

    def _enqueue_monitor_summaries(self, monitors, hours):
        from camp.apps.summaries.tasks import summarize_monitor_hour
        self.stdout.write('\nEnqueuing hourly monitor summaries...')
        self.stdout.flush()

        # Each entry model only for the monitors whose type summarizes it.
        monitor_types = {m.pk: type(m) for m in monitors}
        entry_models = sorted(
            {EntryModel for monitor_type in set(monitor_types.values())
             for EntryModel in monitor_summary_entry_models(monitor_type)},
            key=lambda m: m.entry_type,
        )
        # Checked per monitor's type rather than against Monitor.get_subclasses(),
        # so a bare Monitor row (no subclass) keeps the flag types, as before.
        scoped_ids = {
            EntryModel: [pk for pk, t in monitor_types.items() if is_summarized(t, EntryModel)]
            for EntryModel in entry_models
        }

        count = 0
        for hour in tqdm.tqdm(hours, file=self.stdout, dynamic_ncols=True):
            for EntryModel in entry_models:
                combos = (
                    EntryModel.objects
                    .filter(
                        monitor_id__in=scoped_ids[EntryModel],
                        timestamp__gte=hour,
                        timestamp__lt=hour + timedelta(hours=1),
                    )
                    .filter(
                        Q(stage=Stage.RAW, processor='') |
                        Q(stage=Stage.CALIBRATED)
                    )
                    .values_list('monitor_id', 'processor')
                    .distinct()
                )
                for monitor_id, processor in combos:
                    summarize_monitor_hour(str(monitor_id), hour, EntryModel.entry_type, processor)
                    count += 1
        self.stdout.write(f'  → {count:,} tasks enqueued')

    def _enqueue_region_summaries(self, region_ids, hours, entry_models):
        from camp.apps.summaries.tasks import summarize_region_hour
        self.stdout.write('\nEnqueuing hourly region summaries...')
        self.stdout.flush()
        count = 0
        for hour in tqdm.tqdm(hours, file=self.stdout, dynamic_ncols=True):
            for region_id in region_ids:
                for EntryModel in entry_models:
                    summarize_region_hour(str(region_id), hour, EntryModel.entry_type)
                    count += 1
        self.stdout.write(f'  → {count:,} tasks enqueued')

    def _enqueue_monitor_rollups(self, start, end, now):
        from camp.apps.summaries.tasks import (
            daily_monitor_summaries, monthly_monitor_summaries,
            quarterly_monitor_summaries, seasonal_monitor_summaries,
            yearly_monitor_summaries,
        )
        self.stdout.write('\nEnqueuing monitor rollups...')
        self.stdout.flush()
        windows = [
            (daily_monitor_summaries,     'day',           finished_period_starts('day', start, end, now)),
            (monthly_monitor_summaries,   'month_start',   finished_period_starts('month', start, end, now)),
            (quarterly_monitor_summaries, 'quarter_start', finished_period_starts('quarter', start, end, now)),
            (seasonal_monitor_summaries,  'season_start',  finished_period_starts('season', start, end, now)),
            (yearly_monitor_summaries,    'year_start',    finished_period_starts('year', start, end, now)),
        ]
        count = 0
        for task_fn, kwarg, window_iter in windows:
            for window in window_iter:
                task_fn(**{kwarg: window})
                count += 1
        self.stdout.write(f'  → {count:,} tasks enqueued')

    def _enqueue_region_rollups(self, start, end, now):
        from camp.apps.summaries.tasks import (
            daily_region_summaries, monthly_region_summaries,
            quarterly_region_summaries, seasonal_region_summaries,
            yearly_region_summaries,
        )
        self.stdout.write('\nEnqueuing region rollups...')
        self.stdout.flush()
        windows = [
            (daily_region_summaries,     'day',           finished_period_starts('day', start, end, now)),
            (monthly_region_summaries,   'month_start',   finished_period_starts('month', start, end, now)),
            (quarterly_region_summaries, 'quarter_start', finished_period_starts('quarter', start, end, now)),
            (seasonal_region_summaries,  'season_start',  finished_period_starts('season', start, end, now)),
            (yearly_region_summaries,    'year_start',    finished_period_starts('year', start, end, now)),
        ]
        count = 0
        for task_fn, kwarg, window_iter in windows:
            for window in window_iter:
                task_fn(**{kwarg: window})
                count += 1
        self.stdout.write(f'  → {count:,} tasks enqueued')

    # ---- Date helpers ----

    def _parse_date(self, value):
        d = parse_date(value)
        if d is None:
            raise CommandError(f'Invalid date: {value!r}. Use YYYY-MM-DD.')
        return make_aware(datetime(d.year, d.month, d.day), settings.DEFAULT_TIMEZONE)
