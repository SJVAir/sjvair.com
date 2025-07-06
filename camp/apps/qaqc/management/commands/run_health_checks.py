from datetime import datetime, timedelta

from django.core.management.base import BaseCommand
from django.utils.timezone import make_aware, now

from camp.apps.entries.models import PM25
from camp.apps.monitors.models import Monitor
from camp.apps.qaqc import tasks
from camp.apps.qaqc.models import HealthCheck


class Command(BaseCommand):
    help = 'Run QA/QC health checks for a given hour and monitor(s).'

    def add_arguments(self, parser):
        parser.add_argument(
            'date',
            nargs='?',
            help='ISO timestamp (e.g. 2025-07-04T14:00). Defaults to current hour.',
        )
        parser.add_argument(
            '--monitor_id',
            help='Run health check for a specific monitor ID.',
        )
        parser.add_argument(
            '--all',
            action='store_true',
            help='Run health checks for all multi-sensor monitors.',
        )

    def handle(self, *args, **options):
        hour = self.parse_hour(options['date'])

        if options['monitor_id']:
            tasks.monitor_health_check.call_local(options['monitor_id'], hour)
            self.stdout.write(f'✓ Evaluated {monitor} @ {hour:%Y-%m-%d %H:00}')
            return

        if options['all']:
            count = 0
            tasks.hourly_health_checks(hour, call_local=True)

            self.stdout.write(f'✓ Evaluated {count} monitors @ {hour:%Y-%m-%d %H:00}')
            return

        self.stderr.write('Error: must specify --monitor_id or --all')
        self.stderr.write('Use `--help` for more info.')

    def parse_hour(self, date_str):
        if not date_str:
            return now().replace(minute=0, second=0, microsecond=0)

        try:
            dt = make_aware(datetime.fromisoformat(date_str))
            return dt.replace(minute=0, second=0, microsecond=0)
        except ValueError:
            raise CommandError(f'Invalid date format: {date_str}')
