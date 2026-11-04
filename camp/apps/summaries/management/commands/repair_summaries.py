from datetime import datetime

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.utils.dateparse import parse_date

from camp.apps.summaries import repair
from camp.utils.datetime import make_aware


class Command(BaseCommand):
    help = (
        'Repair daily-and-longer summaries in a date range: delete rows that do not start '
        'on a Pacific period boundary, optionally fill missing hourly region rows, then '
        're-roll. Always scoped by monitor and/or region.'
    )

    def add_arguments(self, parser):
        parser.add_argument('start', help='Start date, Pacific (YYYY-MM-DD)')
        parser.add_argument('end', help='End date, Pacific, exclusive (YYYY-MM-DD)')
        parser.add_argument('--monitor', action='append', default=[], metavar='PK',
            help='Repair this monitor\'s summaries (repeatable)')
        parser.add_argument('--monitor-type', action='append', default=[], metavar='TYPE',
            help='Repair every monitor of this type, e.g. purpleair (repeatable)')
        parser.add_argument('--region', action='append', default=[], metavar='PK',
            help='Repair this region\'s summaries (repeatable)')
        parser.add_argument('--region-type', action='append', default=[], metavar='TYPE',
            help='Repair every current region of this type with a boundary, e.g. county (repeatable)')
        parser.add_argument('--region-hours', action='store_true',
            help='First compute hourly region rows missing for hours that have monitor rows')
        parser.add_argument('--dry-run', action='store_true',
            help='Report what would change and write nothing')

    def handle(self, *args, **options):
        start = self._parse_date(options['start'])
        end = self._parse_date(options['end'])
        if start >= end:
            raise CommandError('start must be before end')

        monitor_flags = options['monitor'] or options['monitor_type']
        region_flags = options['region'] or options['region_type']
        if not (monitor_flags or region_flags):
            raise CommandError(
                'Give a scope: --monitor, --monitor-type, --region or --region-type.'
            )
        if options['region_hours'] and not region_flags:
            raise CommandError('--region-hours needs --region or --region-type.')

        monitor_ids = self._monitor_ids(options['monitor'], options['monitor_type'])
        region_ids = self._region_ids(options['region'], options['region_type'])
        dry_run = options['dry_run']
        now = timezone.now()

        wide_start, wide_end = repair.repair_range(start, end, now)
        windows = repair.reroll_windows(start, end, now)
        scopes = []
        if monitor_flags:
            scopes.append(('monitor', monitor_ids))
        if region_flags:
            scopes.append(('region', region_ids))

        self.stdout.write(f'Range: {self._fmt(start)} -> {self._fmt(end)}')
        if (wide_start, wide_end) != (start, end):
            self.stdout.write(
                f'Day and month rows: {self._fmt(wide_start)} -> {self._fmt(wide_end)} '
                '(the finished periods that overlap the range)'
            )
        self.stdout.write(f'Monitors: {len(monitor_ids):,} | Regions: {len(region_ids):,}')
        if dry_run:
            self.stdout.write('Dry run: nothing will be written.')

        # 1. Missing hourly region rows
        if options['region_hours']:
            missing = repair.missing_region_hours(region_ids, start, end)
            hours = sum(len(v) for v in missing.values())
            line = f'region hour: {hours:,} missing hours in {len(missing):,} region(s)'
            if not dry_run:
                written = repair.fill_region_hours(missing)
                line += f', {written:,} rows written'
            self.stdout.write(line)

        # 2. Delete misaligned rows
        verb = 'to delete' if dry_run else 'deleted'
        for kind, ids in scopes:
            model, ids_field, _ = repair.KINDS[kind]
            misaligned = repair.find_misaligned(model, ids_field, ids, wide_start, wide_end)
            counts = repair.delete_misaligned(kind, ids, misaligned, dry_run=dry_run)
            for resolution in repair.RESOLUTIONS:
                self.stdout.write(f'{kind} {resolution}: {counts[resolution]:,} misaligned {verb}')

        # 3. Re-roll
        for kind, ids in scopes:
            if dry_run:
                counts = {res: len(w) if ids else 0 for res, w in windows.items()}
            else:
                counts = repair.reroll(kind, ids, start, end, now, windows=windows)
            verb = 'windows to roll' if dry_run else 'windows rolled'
            for resolution in repair.RESOLUTIONS:
                self.stdout.write(f'{kind} {resolution}: {counts[resolution]:,} {verb}')

        self.stdout.write(self.style.SUCCESS('Dry run done.' if dry_run else 'Done.'))

    def _monitor_ids(self, pks, types):
        from camp.apps.monitors.models import Monitor

        ids = []
        for pk in pks:
            try:
                found = Monitor.objects.filter(pk=pk).values_list('pk', flat=True).first()
            except (ValueError, TypeError, ValidationError):
                found = None
            if found is None:
                raise CommandError(f'Monitor not found: {pk}')
            ids.append(found)

        valid = sorted({sub.monitor_type for sub in Monitor.get_subclasses()})
        for monitor_type in types:
            if monitor_type not in valid:
                raise CommandError(f'Unknown monitor type: {monitor_type} (valid: {", ".join(valid)})')
            ids.extend(
                Monitor.objects
                .filter(**{f'{monitor_type}__isnull': False})
                .values_list('pk', flat=True)
            )
        return list(dict.fromkeys(ids))

    def _region_ids(self, pks, types):
        from camp.apps.regions.models import Region

        ids = []
        for pk in pks:
            try:
                found = Region.all_objects.filter(pk=pk).values_list('pk', flat=True).first()
            except (ValueError, TypeError, ValidationError):
                found = None
            if found is None:
                raise CommandError(f'Region not found: {pk}')
            ids.append(found)

        valid = list(Region.Type.values)
        for region_type in types:
            if region_type not in valid:
                raise CommandError(f'Unknown region type: {region_type} (valid: {", ".join(valid)})')
            ids.extend(
                Region.objects
                .filter(type=region_type, boundary__isnull=False)
                .values_list('pk', flat=True)
            )
        return list(dict.fromkeys(ids))

    def _parse_date(self, value):
        d = parse_date(value)
        if d is None:
            raise CommandError(f'Invalid date: {value!r}. Use YYYY-MM-DD.')
        return make_aware(datetime(d.year, d.month, d.day), settings.DEFAULT_TIMEZONE)

    def _fmt(self, ts):
        return timezone.localtime(ts, settings.DEFAULT_TIMEZONE).isoformat()
