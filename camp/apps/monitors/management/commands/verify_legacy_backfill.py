import random
from datetime import datetime, timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.utils.dateparse import parse_date

from camp.utils.datetime import make_aware
from camp.apps.monitors.legacy_verify import COUNTERS, EXPECTATIONS, monitors_with_legacy_data, verify


class Command(BaseCommand):
    help = (
        'Read-only check that legacy Entry rows were copied into the entries app '
        'correctly: coverage, values, units, sensor/location/position, and pipeline '
        'state. Compares against expectations written independently of the backfill '
        'mapping, and separates mismatches on backfilled rows from mismatches on '
        'live-ingested rows (which indicate a mapping error).'
    )

    def add_arguments(self, parser):
        types = sorted(cls.__name__.lower() for cls in EXPECTATIONS)
        parser.add_argument('--from', dest='date_from', metavar='YYYY-MM-DD', required=True,
            help='Earliest date to verify (inclusive)')
        parser.add_argument('--to', dest='date_to', metavar='YYYY-MM-DD',
            help='Latest date to verify, exclusive (default: now)')
        parser.add_argument('--type', dest='types', action='append', choices=types,
            help='Monitor type to verify; repeatable (default: all backfilled types)')
        parser.add_argument('--monitor', dest='monitor_id', metavar='MONITOR_ID',
            help='Verify a single monitor, by id')
        parser.add_argument('--sample', type=int, metavar='N',
            help='Verify N random monitors per type that have legacy data in the range')
        parser.add_argument('--seed', type=int,
            help='Random seed for --sample, to repeat a run')
        parser.add_argument('--show-mismatches', dest='show', type=int, default=10, metavar='N',
            help='Example problem rows to print (default: 10)')
        parser.add_argument('--live-lag-hours', dest='live_lag', type=float, default=24,
            help='Rows created within this many hours of their timestamp count as live-ingested (default: 24)')

    def handle(self, *args, **options):
        range_start = self._parse_date(options['date_from'])
        range_end = self._parse_date(options['date_to']) if options['date_to'] else timezone.now()
        if range_start >= range_end:
            raise CommandError('--from must be before --to')
        if options['sample'] is not None and options['sample'] < 1:
            raise CommandError('--sample must be at least 1')

        classes = [
            cls for cls in EXPECTATIONS
            if not options['types'] or cls.__name__.lower() in options['types']
        ]
        rng = random.Random(options['seed'])

        if options['monitor_id']:
            try:
                classes[0].objects.filter(pk=options['monitor_id']).exists()
            except ValidationError:
                raise CommandError(f"Invalid monitor id {options['monitor_id']!r}")

        monitors = []
        for monitor_cls in classes:
            if options['monitor_id']:
                monitors.extend(monitor_cls.objects.filter(pk=options['monitor_id']))
                continue
            ids = sorted(monitors_with_legacy_data(monitor_cls, range_start, range_end))
            if options['sample'] and len(ids) > options['sample']:
                ids = rng.sample(ids, options['sample'])
            self.stdout.write(f'{monitor_cls.__name__}: verifying {len(ids)} monitor(s)')
            monitors.extend(monitor_cls.objects.filter(pk__in=ids))

        if options['monitor_id'] and not monitors:
            raise CommandError(f"No backfilled monitor found with id {options['monitor_id']!r}")

        report = verify(
            monitors, range_start, range_end,
            live_lag=timedelta(hours=options['live_lag']),
            max_examples=options['show'],
        )
        self._print(report)

        if report.failed:
            raise CommandError('Verification found problems (see above).')
        self.stdout.write(self.style.SUCCESS('PASS: every legacy row checked has a matching RAW entry.'))

    def _print(self, report):
        headers = ('type', 'entry') + COUNTERS
        rows = [
            key + tuple(str(report.counts[key][name]) for name in COUNTERS)
            for key in sorted(report.counts)
        ]
        widths = [max(len(str(cell)) for cell in column) for column in zip(headers, *rows)]
        for row in (headers, *rows):
            self.stdout.write('  '.join(str(cell).ljust(width) for cell, width in zip(row, widths)))

        if report.examples:
            self.stdout.write('')
            self.stdout.write('Examples:')
            for example in report.examples:
                self.stdout.write(
                    f'  [{example.kind}] {example.entry_type} monitor={example.monitor_id} '
                    f'{example.timestamp:%Y-%m-%d %H:%M:%S%z} sensor={example.sensor!r}: {example.detail}'
                )

    def _parse_date(self, value):
        try:
            d = parse_date(value)
        except ValueError:
            d = None
        if d is None:
            raise CommandError(f'Invalid date: {value!r}. Use YYYY-MM-DD.')
        return make_aware(datetime(d.year, d.month, d.day), settings.DEFAULT_TIMEZONE)
