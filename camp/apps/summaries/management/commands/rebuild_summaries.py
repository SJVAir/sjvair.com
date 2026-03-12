import calendar
import sys
from datetime import datetime, timedelta

import tqdm

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.utils.dateparse import parse_date

from camp.utils.datetime import make_aware
from camp.apps.summaries.aggregators import compute_monitor_summary, compute_region_summary
from camp.apps.summaries.models import BaseSummary, MonitorSummary, RegionSummary
from camp.apps.summaries.tasks import (
    get_summarizable_entry_models,
    rollup_monitor_summaries,
    rollup_region_summaries,
)


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

    def handle(self, *args, **options):
        from camp.apps.monitors.models import Monitor
        from camp.apps.regions.models import Region

        start = self._parse_date(options['start'])
        end = (
            self._parse_date(options['end'])
            if options['end']
            else timezone.now().replace(minute=0, second=0, microsecond=0)
        )

        if start >= end:
            raise CommandError('start must be before end')

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
            region = Region.objects.filter(pk=region_id).first()
            if not region:
                raise CommandError(f'Region not found: {region_id}')
            if not region.boundary:
                raise CommandError(f'Region {region_id} has no boundary geometry')
            monitors = Monitor.objects.filter(position__within=region.boundary.geometry)
        else:
            monitors = Monitor.objects.all()

        monitor_ids = list(monitors.values_list('pk', flat=True))

        # Determine region scope
        if region_id:
            regions = Region.objects.filter(pk=region_id)
        elif monitor_id:
            monitor = monitors.first()
            regions = monitor.regions if monitor else Region.objects.none()
        else:
            regions = Region.objects.all()

        region_ids = list(regions.values_list('pk', flat=True))

        hours = list(self._iter_hours(start, end))
        entry_models = get_summarizable_entry_models()

        self.stdout.write(
            f'Date range: {start:%Y-%m-%d %H:%M} → {end:%Y-%m-%d %H:%M} '
            f'({len(hours):,} hours)'
        )
        self.stdout.write(f'Monitors: {len(monitor_ids):,} | Regions: {len(region_ids):,}')
        self.stdout.flush()

        # Monitor summaries
        if not regions_only:
            monitors_by_id = {m.pk: m for m in monitors}
            self._backfill_monitor_summaries(monitors_by_id, hours, entry_models)
            self._rollup(rollup_monitor_summaries, 'monitor', monitor_ids, start, end)

        # Region summaries
        if not monitors_only:
            self._backfill_region_summaries(list(regions), hours)
            self._rollup(rollup_region_summaries, 'region', region_ids, start, end)

        self.stdout.write(self.style.SUCCESS('Done.'))

    def _backfill_monitor_summaries(self, monitors_by_id, hours, entry_models):
        monitor_ids = list(monitors_by_id.keys())
        self.stdout.write(f'\nComputing hourly monitor summaries...')
        self.stdout.flush()

        for hour in tqdm.tqdm(hours, file=self.stdout, dynamic_ncols=True):
            for EntryModel in entry_models:
                from django.db.models import Q
                from camp.apps.entries.stages import Stage
                combos = (
                    EntryModel.objects
                    .filter(
                        monitor_id__in=monitor_ids,
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
                for mon_id, processor in combos:
                    monitor = monitors_by_id[mon_id]
                    stats = compute_monitor_summary(monitor, hour, EntryModel, processor)
                    if stats is None:
                        continue
                    MonitorSummary.objects.update_or_create(
                        monitor_id=mon_id,
                        timestamp=hour,
                        resolution=BaseSummary.Resolution.HOURLY,
                        entry_type=EntryModel.entry_type,
                        processor=processor,
                        defaults=stats,
                    )

    def _backfill_region_summaries(self, regions, hours):
        self.stdout.write(f'\nComputing hourly region summaries...')
        self.stdout.flush()

        for hour in tqdm.tqdm(hours, file=self.stdout, dynamic_ncols=True):
            entry_types = list(
                MonitorSummary.objects
                .filter(timestamp=hour, resolution=BaseSummary.Resolution.HOURLY)
                .values_list('entry_type', flat=True)
                .distinct()
            )
            for region in regions:
                for entry_type in entry_types:
                    stats = compute_region_summary(region, hour, entry_type)
                    if stats is None:
                        continue
                    RegionSummary.objects.update_or_create(
                        region=region,
                        timestamp=hour,
                        resolution=BaseSummary.Resolution.HOURLY,
                        entry_type=entry_type,
                        defaults=stats,
                    )

    def _rollup(self, rollup_fn, label, ids, start, end):
        R = BaseSummary.Resolution
        levels = [
            ('daily',     R.DAILY,     R.HOURLY,  list(self._iter_days(start, end))),
            ('monthly',   R.MONTHLY,   R.DAILY,   list(self._iter_months(start, end))),
            ('quarterly', R.QUARTERLY, R.MONTHLY, list(self._iter_quarters(start, end))),
            ('seasonal',  R.SEASONAL,  R.MONTHLY, list(self._iter_seasons(start, end))),
            ('yearly',    R.YEARLY,    R.MONTHLY, list(self._iter_years(start, end))),
        ]
        for name, target, source, windows in levels:
            if not windows:
                continue
            self.stdout.write(f'\nRolling up {name} {label} summaries ({len(windows):,} windows)...')
            self.stdout.flush()
            for window_start in tqdm.tqdm(windows, file=self.stdout, dynamic_ncols=True):
                window_end = self._window_end(target, window_start)
                rollup_fn(target, source, window_start, window_end, **{f'{label}_ids': ids})

    # ---- Date helpers ----

    def _parse_date(self, value):
        d = parse_date(value)
        if d is None:
            raise CommandError(f'Invalid date: {value!r}. Use YYYY-MM-DD.')
        return make_aware(datetime(d.year, d.month, d.day))

    def _window_end(self, resolution, window_start):
        R = BaseSummary.Resolution
        if resolution == R.DAILY:
            return window_start + timedelta(days=1)
        if resolution == R.MONTHLY:
            _, days = calendar.monthrange(window_start.year, window_start.month)
            return window_start + timedelta(days=days)
        if resolution in (R.QUARTERLY, R.SEASONAL):
            return window_start + timedelta(days=92)
        if resolution == R.YEARLY:
            return window_start.replace(year=window_start.year + 1)

    def _iter_hours(self, start, end):
        current = start
        while current < end:
            yield current
            current += timedelta(hours=1)

    def _iter_days(self, start, end):
        day = start.replace(hour=0, minute=0, second=0, microsecond=0)
        end_day = end.replace(hour=0, minute=0, second=0, microsecond=0)
        while day <= end_day:
            yield day
            day += timedelta(days=1)

    def _iter_months(self, start, end):
        month = start.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        while month <= end:
            yield month
            if month.month == 12:
                month = month.replace(year=month.year + 1, month=1)
            else:
                month = month.replace(month=month.month + 1)

    def _iter_quarters(self, start, end):
        # Quarter starts: Jan, Apr, Jul, Oct
        month = start.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        # Rewind to the start of the current quarter
        month = month.replace(month=((month.month - 1) // 3) * 3 + 1)
        while month <= end:
            yield month
            next_month = month.month + 3
            if next_month > 12:
                month = month.replace(year=month.year + 1, month=next_month - 12)
            else:
                month = month.replace(month=next_month)

    def _iter_seasons(self, start, end):
        # Season starts: Dec, Mar, Jun, Sep
        season_start_months = {12, 3, 6, 9}
        month = start.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        # Rewind to the previous season start
        while month.month not in season_start_months:
            if month.month == 1:
                month = month.replace(year=month.year - 1, month=12)
            else:
                month = month.replace(month=month.month - 1)
        while month <= end:
            yield month
            next_month = month.month + 3
            if next_month > 12:
                month = month.replace(year=month.year + 1, month=next_month - 12)
            else:
                month = month.replace(month=next_month)

    def _iter_years(self, start, end):
        year = start.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        while year <= end:
            yield year
            year = year.replace(year=year.year + 1)
