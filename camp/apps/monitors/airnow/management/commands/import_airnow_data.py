from datetime import datetime

from django.core.management.base import BaseCommand, CommandError

from camp.apps.monitors.airnow.tasks import import_airnow_data
from camp.utils.datetime import make_aware


class Command(BaseCommand):
    help = (
        'Import data from AirNow.gov. With no options, fetches the same recent '
        'window as the periodic task; with --start/--end, re-fetches that range '
        '(existing entries are updated in place).'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--start',
            help='ISO timestamp (e.g. 2025-07-04T14:00). Naive values are treated as UTC.',
        )
        parser.add_argument(
            '--end',
            help='ISO timestamp (exclusive). Defaults to now.',
        )

    def handle(self, *args, **options):
        start = self.parse_timestamp(options['start'])
        end = self.parse_timestamp(options['end'])

        if start and end and start >= end:
            raise CommandError('--start must be before --end')

        import_airnow_data.call_local(start_date=start, end_date=end)

    def parse_timestamp(self, value):
        if not value:
            return None
        try:
            return make_aware(datetime.fromisoformat(value))
        except ValueError:
            raise CommandError(f'Invalid timestamp: {value}')
