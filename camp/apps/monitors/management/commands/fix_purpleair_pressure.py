from datetime import datetime
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils.dateparse import parse_date

from camp.utils.datetime import make_aware
from camp.apps.entries.models import Pressure
from camp.apps.monitors.models import Entry
from camp.apps.monitors.purpleair.models import PurpleAir


class Command(BaseCommand):
    help = (
        'One-time repair for PurpleAir Pressure RAW entries created by the old '
        'migrate_legacy_entry path, which copied legacy pressure (hPa) directly '
        'into `value` (mmHg) with no unit conversion. Recomputes each entry from '
        'its legacy source and updates in place if the value is wrong.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
            help='Report how many entries would be corrected without saving changes')
        parser.add_argument('--monitor', dest='monitor_id', metavar='MONITOR_ID',
            help='Limit to a single PurpleAir monitor, by id')
        parser.add_argument('--from', dest='date_from', metavar='YYYY-MM-DD',
            help='Earliest timestamp to check (inclusive)')
        parser.add_argument('--to', dest='date_to', metavar='YYYY-MM-DD',
            help='Latest timestamp to check (exclusive)')

    def handle(self, *args, **options):
        dry_run = options['dry_run']
        corrected = 0
        checked = 0

        monitors = PurpleAir.objects.all()
        if options['monitor_id']:
            monitors = monitors.filter(pk=options['monitor_id'])
            if not monitors.exists():
                raise CommandError(f"No PurpleAir monitor found with id {options['monitor_id']!r}")

        date_from = self._parse_date(options['date_from']) if options['date_from'] else None
        date_to = self._parse_date(options['date_to']) if options['date_to'] else None
        if date_from and date_to and date_from >= date_to:
            raise CommandError('--from must be before --to')

        for monitor in monitors.iterator(chunk_size=100):
            pressure_qs = Pressure.objects.filter(monitor=monitor, stage=Pressure.Stage.RAW)
            legacy_qs = Entry.objects.filter(monitor=monitor, pressure__isnull=False)
            if date_from:
                pressure_qs = pressure_qs.filter(timestamp__gte=date_from)
                legacy_qs = legacy_qs.filter(timestamp__gte=date_from)
            if date_to:
                pressure_qs = pressure_qs.filter(timestamp__lt=date_to)
                legacy_qs = legacy_qs.filter(timestamp__lt=date_to)

            # One query per monitor for its legacy pressures (not one per Pressure row) --
            # sensor 'a'/'b' rows carry the same pressure value, so last-write-wins is fine.
            legacy_by_timestamp = dict(legacy_qs.values_list('timestamp', 'pressure'))
            if not legacy_by_timestamp:
                continue

            for entry in pressure_qs.iterator(chunk_size=1000):
                checked += 1
                legacy_pressure = legacy_by_timestamp.get(entry.timestamp)
                if legacy_pressure is None:
                    continue

                correct_value = (legacy_pressure / Decimal('1.33322')).quantize(Decimal('0.01'))
                if entry.value == correct_value:
                    continue

                corrected += 1
                if not dry_run:
                    entry.value = correct_value
                    entry.save(update_fields=['value'])

        verb = 'Would correct' if dry_run else 'Corrected'
        self.stdout.write(self.style.SUCCESS(f'{verb} {corrected} of {checked} checked entries.'))

    def _parse_date(self, value):
        try:
            d = parse_date(value)
        except ValueError:
            d = None
        if d is None:
            raise CommandError(f'Invalid date: {value!r}. Use YYYY-MM-DD.')
        return make_aware(datetime(d.year, d.month, d.day), settings.DEFAULT_TIMEZONE)
