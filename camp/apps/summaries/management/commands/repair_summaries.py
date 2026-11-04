from datetime import datetime, timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.utils.dateparse import parse_date

from camp.apps.summaries import repair
from camp.apps.summaries.periods import period_end
from camp.utils.datetime import make_aware


def _count(n, noun):
    """'1 period', '2 periods', '1,024 missing hours'."""
    return f'{n:,} {noun}' if n == 1 else f'{n:,} {noun}s'


class Command(BaseCommand):
    help = (
        'Repair daily-and-longer summaries in a date range: optionally fill missing hourly '
        'region rows, then per resolution from days up delete the rows that do not start on '
        'a Pacific period boundary and re-roll it. Always scoped by monitor and/or region.'
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
            help='First compute hourly region rows missing for hours that have monitor rows, '
                 'in only [start, end): day and month re-rolls that widen past it read the '
                 'region hours already there')
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
        if options['region_hours']:
            self.stdout.write(
                f'Region hours: fills missing hourly region rows {self._fmt(start)} -> {self._fmt(end)} only; '
                'day and month re-rolls outside it read the region hours already there'
            )
        self.stdout.write(
            f'Scanning for misaligned rows: {self._fmt(scan_start - timedelta(days=1))} -> {self._fmt(scan_end)}'
        )
        for resolution, span in spans.items():
            unfinished = len(span.periods) - len(span.rolled)
            self.stdout.write(
                f'  {resolution}: deletes misaligned rows standing for the {_count(len(span.periods), "period")} '
                f'{self._fmt(span.periods[0])} -> {self._fmt(period_end(resolution, span.periods[-1]))}; '
                f're-rolls the {len(span.rolled):,} finished'
                + (f' ({unfinished:,} unfinished left for the scheduled rollup)' if unfinished else '')
            )
        if dry_run:
            self.stdout.write('Dry run: nothing will be written.')

        # 1. Missing hourly region rows
        if options['region_hours']:
            missing = repair.missing_region_hours(region_ids, start, end, progress=progress)
            hours = sum(len(v) for v in missing.values())
            line = f'region hour: {_count(hours, "missing hour")} in {_count(len(missing), "region")}'
            if not dry_run:
                written = repair.fill_region_hours(missing, progress=progress)
                line += f', {_count(written, "row")} written'
            self.stdout.write(line)

        # 2. Per kind, per resolution from days up: delete the misaligned rows
        # standing for a covered period, then re-roll that resolution, so a
        # resolution's old rows are missing only while it re-rolls. Each
        # resolution reads only the one below, which is already done.
        for kind, ids in scopes:
            model, ids_field, _ = repair.KINDS[kind]
            misaligned = repair.find_misaligned(model, ids_field, ids, scan_start, scan_end)
            decision = repair.decide(spans, misaligned)
            beyond, held = repair.split_outside(spans, decision.outside)
            for resolution in repair.RESOLUTIONS:
                self._repair_resolution(kind, ids, resolution, decision, beyond, held,
                                        start, end, now, dry_run, progress)

        self.stdout.write(self.style.SUCCESS('Dry run done.' if dry_run else 'Done.'))

    def _repair_resolution(self, kind, ids, resolution, decision, beyond, held, start, end, now, dry_run, progress):
        delete = {resolution: decision.delete.get(resolution, [])}
        counts = repair.delete_misaligned(kind, ids, delete, dry_run=dry_run, progress=progress)
        far = repair.delete_misaligned(kind, ids, {resolution: beyond.get(resolution, [])}, dry_run=True)
        kept = repair.delete_misaligned(kind, ids, {resolution: held.get(resolution, [])}, dry_run=True)
        verb = 'to delete' if dry_run else 'deleted'
        self.stdout.write(
            f'{kind} {resolution}: {counts[resolution]:,} misaligned {verb}, '
            f'{far[resolution]:,} left in place (period outside this run), '
            f'{kept[resolution]:,} left in place (period skipped)'
        )
        self._list_left(kind, resolution, beyond.get(resolution, []),
                        'outside this run; widen the range to repair it')
        self._list_left(kind, resolution, held.get(resolution, []),
                        'which this run skips (see skipped)')
        causes = decision.causes.get(resolution, {})
        for p in decision.skipped.get(resolution, []):
            what, source, ts = causes[p]
            reason = (
                f'its window holds the {source} row at {self._fmt(ts)}, left in place' if what == 'row'
                else f'its window holds the skipped {source} starting {self._fmt(ts)}'
            )
            self.stdout.write(
                f'  skipped: {kind} {resolution} starting {self._fmt(p)} is not deleted or re-rolled: {reason}'
            )

        windows = decision.windows
        if dry_run:
            rolled = len(windows.get(resolution, [])) if ids else 0
            verb = 'to roll'
        else:
            rolled = repair.reroll(kind, ids, start, end, now, windows=windows,
                                   resolutions=[resolution], progress=progress)[resolution]
            verb = 'rolled'
        self.stdout.write(f'{kind} {resolution}: {_count(rolled, "window")} {verb}')

    def _list_left(self, kind, resolution, timestamps, why):
        for ts in timestamps[:10]:
            self.stdout.write(
                f'  left in place: {kind} {resolution} at {self._fmt(ts)} stands for the period '
                f'starting {self._fmt(repair.stands_for(resolution, ts))}, {why}'
            )
        if len(timestamps) > 10:
            self.stdout.write(f'  left in place: ... and {len(timestamps) - 10:,} more timestamps')

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
