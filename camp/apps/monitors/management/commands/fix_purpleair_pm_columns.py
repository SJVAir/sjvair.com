import time
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Min

from camp.apps.entries import models as entry_models
from camp.apps.monitors.legacy_backfill import PM_COLUMN_CUTOVER
from camp.apps.monitors.purpleair.models import PurpleAir


class Command(BaseCommand):
    help = (
        "Repair PurpleAir RAW PM1.0 (entries PM10) / PM10.0 (entries PM100) rows "
        "written before 2022-04-01 with the two values crossed. Migration 0020 "
        "renamed the legacy pm10/pm100 columns crosswise without moving data, so "
        "rows copied from legacy storage by an older path hold PM1.0 in the PM100 "
        "table and vice versa. PM1.0 is a subset of PM10.0 and can never be the "
        "larger, so every (monitor, sensor, timestamp) pair where PM10 > PM100 has "
        "its two values swapped. Ordered pairs (including correct rows from the "
        "PurpleAir history import) and unpaired rows are left alone. Works per "
        "monitor in time windows, one transaction per window, and prints progress "
        "so a Heroku one-off dyno isn't killed for silence. Idempotent and "
        "resumable: a second run finds nothing to swap. PM10/PM100 are RAW-only "
        "for PurpleAir (no derived entries), and rows are updated in place, so "
        "LatestEntry (which points at entries by id) stays valid."
    )

    def add_arguments(self, parser):
        parser.add_argument('--window-days', type=int, default=30,
            help='Days of history per query / transaction (default: 30).')
        parser.add_argument('--sleep', type=float, default=0.0,
            help='Seconds to pause between windows to ease load (default: 0).')
        parser.add_argument('--monitor-id', dest='monitor_ids', action='append', default=[],
            help='Restrict to this PurpleAir monitor id. Repeatable.')
        parser.add_argument('--dry-run', action='store_true',
            help='Count what would change; write nothing.')

    def handle(self, *args, **options):
        window = timedelta(days=options['window_days'])
        if window <= timedelta(0):
            raise CommandError('--window-days must be positive')
        sleep = options['sleep']
        dry_run = options['dry_run']

        monitors = PurpleAir.objects.order_by('pk')
        if options['monitor_ids']:
            monitors = monitors.filter(pk__in=options['monitor_ids'])
            if not monitors.exists():
                raise CommandError(f"No PurpleAir monitors found for {options['monitor_ids']!r}")

        started = time.monotonic()
        checked = swapped = 0
        for monitor in monitors:
            monitor_checked, monitor_swapped = self.fix_monitor(monitor, window, sleep, dry_run)
            checked += monitor_checked
            swapped += monitor_swapped

        if not swapped:
            self.stdout.write(f'Checked {checked} pairs: nothing to do')
            return
        verb = 'Would swap' if dry_run else 'Swapped'
        self.stdout.write(self.style.SUCCESS(
            f'{verb} {swapped} of {checked} pairs checked in {time.monotonic() - started:.0f}s'
        ))

    def fix_monitor(self, monitor, window, sleep, dry_run):
        PM10, PM100 = entry_models.PM10, entry_models.PM100
        first = PM10.objects.filter(
            monitor=monitor, stage=PM10.Stage.RAW, timestamp__lt=PM_COLUMN_CUTOVER,
        ).aggregate(first=Min('timestamp'))['first']
        if first is None:
            return 0, 0

        label = f'{monitor.pk} {monitor.name}'
        checked = swapped = 0
        start = first
        while start < PM_COLUMN_CUTOVER:
            end = min(start + window, PM_COLUMN_CUTOVER)
            window_checked, window_swapped = self.fix_window(monitor, start, end, dry_run)
            checked += window_checked
            swapped += window_swapped
            if window_swapped:
                self.stdout.write(f'{label}: {swapped} pairs swapped through {end:%Y-%m-%d}')
                self.stdout.flush()
                if sleep:
                    time.sleep(sleep)
            start = end

        self.stdout.write(f'{label}: {checked} pairs checked, {swapped} {"to swap" if dry_run else "swapped"}')
        self.stdout.flush()
        return checked, swapped

    def fix_window(self, monitor, start, end, dry_run):
        PM10, PM100 = entry_models.PM10, entry_models.PM100

        def raw_rows(model):
            return {
                (row.sensor, row.timestamp): row
                for row in model.objects.filter(
                    monitor=monitor, stage=model.Stage.RAW, timestamp__gte=start, timestamp__lt=end,
                )
            }

        with transaction.atomic():
            pm10_rows = raw_rows(PM10)
            pm100_rows = raw_rows(PM100)

            checked = 0
            crossed = []
            for key, pm10 in pm10_rows.items():
                pm100 = pm100_rows.get(key)
                if pm100 is None:
                    continue
                checked += 1
                if pm10.value > pm100.value:
                    pm10.value, pm100.value = pm100.value, pm10.value
                    crossed.append((pm10, pm100))

            if crossed and not dry_run:
                PM10.objects.bulk_update([pm10 for pm10, _ in crossed], ['value'])
                PM100.objects.bulk_update([pm100 for _, pm100 in crossed], ['value'])

        return checked, len(crossed)
