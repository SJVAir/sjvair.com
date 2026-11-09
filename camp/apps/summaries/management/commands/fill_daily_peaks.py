from collections import Counter

from django.core.management.base import BaseCommand, CommandError

from camp.apps.summaries.management.commands._scope import ScopeMixin
from camp.apps.summaries.peaks import fill_daily_peaks, peak_entry_models
from camp.apps.summaries.periods import iter_period_starts, period_end


class Command(ScopeMixin, BaseCommand):
    help = (
        'Fill max_1h / max_8h on existing daily summary rows (O3, NO2, SO2: max_1h; CO: max_8h) '
        'in a date range, one Pacific month at a time. Always scoped by monitor and/or region.'
    )

    def add_arguments(self, parser):
        parser.add_argument('start', help='Start date, Pacific (YYYY-MM-DD)')
        parser.add_argument('end', help='End date, Pacific, exclusive (YYYY-MM-DD)')
        parser.add_argument('--monitor', action='append', default=[], metavar='PK',
            help='Fill this monitor\'s rows (repeatable)')
        parser.add_argument('--monitor-type', action='append', default=[], metavar='TYPE',
            help='Fill every monitor of this type, e.g. airnow (repeatable)')
        parser.add_argument('--region', action='append', default=[], metavar='PK',
            help='Fill this region\'s rows (repeatable)')
        parser.add_argument('--region-type', action='append', default=[], metavar='TYPE',
            help='Fill every current region of this type with a boundary, e.g. county (repeatable)')
        parser.add_argument('--entry-type', action='append', default=[], metavar='TYPE',
            help='Only this entry type, e.g. o3 (repeatable; default: every peak type)')
        parser.add_argument('--batch-size', type=int, default=1000,
            help='Rows written per batch (default 1000)')
        parser.add_argument('--dry-run', action='store_true',
            help='Report what would change and write nothing')

    def handle(self, *args, **options):
        start = self._parse_date(options['start'])
        end = self._parse_date(options['end'])
        if start >= end:
            raise CommandError('start must be before end')
        if options['batch_size'] < 1:
            raise CommandError(f'--batch-size must be a positive integer, got {options["batch_size"]}')

        monitor_flags = options['monitor'] or options['monitor_type']
        region_flags = options['region'] or options['region_type']
        if not (monitor_flags or region_flags):
            raise CommandError(
                'Give a scope: --monitor, --monitor-type, --region or --region-type.'
            )

        peaks = {m.entry_type: m for m in peak_entry_models()}
        for entry_type in options['entry_type']:
            if entry_type not in peaks:
                raise CommandError(
                    f'Not a peak entry type: {entry_type} (eligible: {", ".join(sorted(peaks))})'
                )
        entry_models = [peaks[t] for t in options['entry_type']] or None

        scopes = []
        if monitor_flags:
            scopes.append(('monitor', self._monitor_ids(options['monitor'], options['monitor_type'])))
        if region_flags:
            scopes.append(('region', self._region_ids(options['region'], options['region_type'])))

        dry_run = options['dry_run']
        progress = self._progress if options['verbosity'] >= 1 else None
        self.stdout.write(f'Range: {self._fmt(start)} -> {self._fmt(end)}')
        if dry_run:
            self.stdout.write('Dry run: nothing will be written.')

        verb = 'would change' if dry_run else 'changed'
        for kind, ids in scopes:
            total = Counter()
            if ids:
                # One Pacific month at a time keeps the writer's per-owner read bounded.
                for month in iter_period_starts('month', start, end):
                    chunk_start = max(month, start)
                    chunk_end = min(period_end('month', month), end)
                    if progress:
                        progress(f'{kind} peaks: {self._fmt(chunk_start)} -> {self._fmt(chunk_end)}')
                    total.update(fill_daily_peaks(
                        kind, ids, chunk_start, chunk_end, entry_models=entry_models,
                        dry_run=dry_run, batch_size=options['batch_size'], progress=progress,
                    ))
            self.stdout.write(f'{kind}s: {len(ids):,}')
            if not total:
                self.stdout.write(f'{kind} peaks: nothing to do')
            for entry_type in sorted(total):
                n = total[entry_type]
                self.stdout.write(f'{kind} {entry_type}: {n:,} {"row" if n == 1 else "rows"} {verb}')

        self.stdout.write(self.style.SUCCESS('Dry run done.' if dry_run else 'Done.'))

    def _progress(self, message):
        self.stdout.write(f'  {message}')
        self.stdout.flush()
