from datetime import datetime, timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.utils.dateparse import parse_date

from camp.apps.summaries import repair
from camp.apps.summaries.periods import period_end
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

        spans = repair.plan(start, end, now)
        scan_start, scan_end = repair.scan_range(spans)
        scopes = []
        if monitor_flags:
            scopes.append(('monitor', monitor_ids))
        if region_flags:
            scopes.append(('region', region_ids))
        progress = self._progress if options['verbosity'] >= 1 else repair._noop

        self.stdout.write(f'Range: {self._fmt(start)} -> {self._fmt(end)}')
        self.stdout.write(f'Monitors: {len(monitor_ids):,} | Regions: {len(region_ids):,}')
        self.stdout.write(
            f'Scanning for misaligned rows: {self._fmt(scan_start - timedelta(days=1))} -> {self._fmt(scan_end)}'
        )
        for resolution, span in spans.items():
            unfinished = len(span.periods) - len(span.rolled)
            self.stdout.write(
                f'  {resolution}: deletes misaligned rows standing for the {len(span.periods):,} '
                f'periods {self._fmt(span.periods[0])} -> {self._fmt(period_end(resolution, span.periods[-1]))}; '
                f're-rolls the {len(span.rolled):,} finished'
                + (f' ({unfinished:,} unfinished left for the scheduled rollup)' if unfinished else '')
            )
        if dry_run:
            self.stdout.write('Dry run: nothing will be written.')

        # 1. Missing hourly region rows
        if options['region_hours']:
            missing = repair.missing_region_hours(region_ids, start, end, progress=progress)
            hours = sum(len(v) for v in missing.values())
            line = f'region hour: {hours:,} missing hours in {len(missing):,} region(s)'
            if not dry_run:
                written = repair.fill_region_hours(missing, progress=progress)
                line += f', {written:,} rows written'
            self.stdout.write(line)

        # 2. Delete misaligned rows standing for a covered period; report the rest
        verb = 'to delete' if dry_run else 'deleted'
        decisions = {}
        for kind, ids in scopes:
            model, ids_field, _ = repair.KINDS[kind]
            misaligned = repair.find_misaligned(model, ids_field, ids, scan_start, scan_end)
            decision = decisions[kind] = repair.decide(spans, misaligned)
            counts = repair.delete_misaligned(kind, ids, decision.delete, dry_run=dry_run, progress=progress)
            left = repair.delete_misaligned(kind, ids, decision.outside, dry_run=True)
            for resolution in repair.RESOLUTIONS:
                self.stdout.write(
                    f'{kind} {resolution}: {counts[resolution]:,} misaligned {verb}, '
                    f'{left[resolution]:,} misaligned outside this run\'s range (left in place)'
                )
                outside = decision.outside.get(resolution, [])
                for ts in outside[:10]:
                    self.stdout.write(
                        f'  outside: {kind} {resolution} at {self._fmt(ts)} stands for the period '
                        f'starting {self._fmt(repair.stands_for(resolution, ts))}; widen the range to repair it'
                    )
                if len(outside) > 10:
                    self.stdout.write(f'  outside: ... and {len(outside) - 10:,} more timestamps')
                for p in decision.skipped.get(resolution, []):
                    self.stdout.write(
                        f'  skipped: {kind} {resolution} starting {self._fmt(p)} is not deleted or re-rolled: '
                        'its window holds a row left in place'
                    )

        # 3. Re-roll
        for kind, ids in scopes:
            windows = decisions[kind].windows
            if dry_run:
                counts = {res: len(w) if ids else 0 for res, w in windows.items()}
            else:
                counts = repair.reroll(kind, ids, start, end, now, windows=windows, progress=progress)
            verb = 'windows to roll' if dry_run else 'windows rolled'
            for resolution in repair.RESOLUTIONS:
                self.stdout.write(f'{kind} {resolution}: {counts[resolution]:,} {verb}')

        self.stdout.write(self.style.SUCCESS('Dry run done.' if dry_run else 'Done.'))

    def _progress(self, message):
        self.stdout.write(f'  {message}')
        self.stdout.flush()

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
