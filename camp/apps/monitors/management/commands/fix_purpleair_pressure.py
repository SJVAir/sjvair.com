import time
from datetime import datetime, timedelta

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.db.models import Max, Min
from django.utils.dateparse import parse_date

from camp.utils.datetime import make_aware
from camp.apps.entries.models import Pressure
from camp.apps.monitors.models import Entry
from camp.apps.monitors.purpleair.models import PurpleAir

# The legacy value as Pressure.mmhg would store it: hPa / 1.33322, two places,
# half away from zero (Postgres numeric round() matches ROUND_HALF_UP).
# Legacy sensor 'a'/'b' rows carry the same pressure, so one per timestamp.
# Values that don't fit Pressure.value (max_digits=6) are legacy glitches; skip.
LEGACY_MMHG = '''
    SELECT DISTINCT ON (timestamp) timestamp, round(pressure / 1.33322, 2) AS value
    FROM {legacy}
    WHERE monitor_id = %(monitor)s AND pressure IS NOT NULL
      AND timestamp >= %(start)s AND timestamp < %(end)s
      AND abs(pressure / 1.33322) < 9999.995
    ORDER BY timestamp, sensor
'''

# Rows of {pressure} whose value disagrees with their legacy source.
WRONG_ROWS = '''
    {pressure}.monitor_id = %(monitor)s AND {pressure}.stage = %(stage)s
      AND {pressure}.timestamp >= %(start)s AND {pressure}.timestamp < %(end)s
      AND {pressure}.timestamp = legacy.timestamp
      AND {pressure}.value <> legacy.value
'''


class Command(BaseCommand):
    help = (
        'One-time repair for PurpleAir Pressure RAW entries created by the old '
        'migrate_legacy_entry path, which copied legacy pressure (hPa) directly '
        'into `value` (mmHg) with no unit conversion. Each RAW row with a legacy '
        'source at the same timestamp is set to that source converted to mmHg, '
        'only where it differs, so rows the live converter wrote are left alone. '
        'Works per monitor in time windows with one set-based UPDATE and one '
        'transaction per window, and prints progress so a Heroku one-off dyno '
        "isn't killed for silence. Idempotent and resumable: a second run finds "
        'nothing to correct. PurpleAir pressure is RAW-only (no derived entries), '
        'and rows are updated in place, so LatestEntry stays valid.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
            help='Count what would be corrected; write nothing.')
        parser.add_argument('--monitor', '--monitor-id', dest='monitor_ids', action='append', default=[],
            metavar='MONITOR_ID', help='Restrict to this PurpleAir monitor id. Repeatable.')
        parser.add_argument('--from', dest='date_from', metavar='YYYY-MM-DD',
            help='Earliest timestamp to check (inclusive)')
        parser.add_argument('--to', dest='date_to', metavar='YYYY-MM-DD',
            help='Latest timestamp to check (exclusive)')
        parser.add_argument('--window-days', type=int, default=30,
            help='Days of history per UPDATE / transaction (default: 30).')
        parser.add_argument('--sleep', type=float, default=0.0,
            help='Seconds to pause between windows that changed rows (default: 0).')

    def handle(self, *args, **options):
        window = timedelta(days=options['window_days'])
        if window <= timedelta(0):
            raise CommandError('--window-days must be positive')

        date_from = self._parse_date(options['date_from']) if options['date_from'] else None
        date_to = self._parse_date(options['date_to']) if options['date_to'] else None
        if date_from and date_to and date_from >= date_to:
            raise CommandError('--from must be before --to')

        monitors = PurpleAir.objects.order_by('pk')
        if options['monitor_ids']:
            monitors = monitors.filter(pk__in=options['monitor_ids'])
            if not monitors.exists():
                raise CommandError(f"No PurpleAir monitors found for {options['monitor_ids']!r}")

        pressure = connection.ops.quote_name(Pressure._meta.db_table)
        legacy = f'({LEGACY_MMHG.format(legacy=connection.ops.quote_name(Entry._meta.db_table))}) AS legacy'
        wrong_rows = WRONG_ROWS.format(pressure=pressure)
        self.count_sql = f'SELECT count(*) FROM {pressure}, {legacy} WHERE {wrong_rows}'
        self.update_sql = f'UPDATE {pressure} SET value = legacy.value FROM {legacy} WHERE {wrong_rows}'

        started = time.monotonic()
        corrected = 0
        for monitor in monitors:
            corrected += self.fix_monitor(
                monitor, date_from, date_to, window, options['sleep'], options['dry_run'],
            )

        verb = 'Would correct' if options['dry_run'] else 'Corrected'
        self.stdout.write(self.style.SUCCESS(
            f'{verb} {corrected} entries in {time.monotonic() - started:.0f}s'
        ))

    def fix_monitor(self, monitor, date_from, date_to, window, sleep, dry_run):
        queryset = Pressure.objects.filter(monitor=monitor, stage=Pressure.Stage.RAW)
        if date_from:
            queryset = queryset.filter(timestamp__gte=date_from)
        if date_to:
            queryset = queryset.filter(timestamp__lt=date_to)
        bounds = queryset.aggregate(first=Min('timestamp'), last=Max('timestamp'))
        if bounds['first'] is None:
            return 0

        label = f'{monitor.pk} {monitor.name}'
        end_of_range = bounds['last'] + timedelta(microseconds=1)
        corrected = 0
        start = bounds['first']
        while start < end_of_range:
            end = min(start + window, end_of_range)
            count = self.fix_window(monitor, start, end, dry_run)
            if count:
                corrected += count
                self.stdout.write(f'{label}: {corrected} corrected through {end:%Y-%m-%d}')
                self.stdout.flush()
                if sleep:
                    time.sleep(sleep)
            start = end

        if corrected:
            self.stdout.write(f'{label}: {corrected} {"to correct" if dry_run else "corrected"}')
            self.stdout.flush()
        return corrected

    def fix_window(self, monitor, start, end, dry_run):
        params = {
            'monitor': PurpleAir._meta.pk.get_db_prep_value(monitor.pk, connection),
            'stage': Pressure.Stage.RAW,
            'start': start,
            'end': end,
        }
        with transaction.atomic(), connection.cursor() as cursor:
            if dry_run:
                cursor.execute(self.count_sql, params)
                return cursor.fetchone()[0]
            cursor.execute(self.update_sql, params)
            return cursor.rowcount

    def _parse_date(self, value):
        try:
            d = parse_date(value)
        except ValueError:
            d = None
        if d is None:
            raise CommandError(f'Invalid date: {value!r}. Use YYYY-MM-DD.')
        return make_aware(datetime(d.year, d.month, d.day), settings.DEFAULT_TIMEZONE)
