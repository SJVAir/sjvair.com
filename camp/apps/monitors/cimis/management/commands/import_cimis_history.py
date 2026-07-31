from datetime import date, timedelta

from django.core.management.base import BaseCommand, CommandError

from camp.apps.monitors.cimis.models import CIMIS
from camp.apps.monitors.cimis.tasks import _ingest_cimis_data


class Command(BaseCommand):
    help = 'Backfill historical CIMIS weather station data for a date range, one day at a time'

    def add_arguments(self, parser):
        parser.add_argument('--start', required=True, type=str, help='Start date YYYY-MM-DD (inclusive)')
        parser.add_argument('--end', required=True, type=str, help='End date YYYY-MM-DD (inclusive)')

    def handle(self, *args, **options):
        try:
            start = date.fromisoformat(options['start'])
            end = date.fromisoformat(options['end'])
        except ValueError:
            raise CommandError('Dates must be in YYYY-MM-DD format.')

        if start > end:
            raise CommandError('--start must not be after --end.')

        if not CIMIS.objects.exists():
            self.stdout.write(self.style.WARNING(
                'No CIMIS stations found -- run discover_cimis_stations first.'
            ))
            return

        day = start
        while day <= end:
            self.stdout.write(f'{day}...')
            _ingest_cimis_data(day)
            day += timedelta(days=1)
