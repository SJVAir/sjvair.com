from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from django.utils.timezone import make_aware, now

from camp.apps.monitors.models import Monitor


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
        if not options['monitor_id'] and not options['all']:
            self.stderr.write('Error: must specify --monitor_id or --all')
            self.stderr.write('Use `--help` for more info.')
            return

        hour = self.parse_hour(options['date'])
        queryset = Monitor.objects.get_for_health_checks()

        if options['monitor_id']:
            queryset = queryset.filter(monitor_id=options['monitor_id'])

        count = queryset.count()
        self.stdout.write(f'Evaluating {count} monitor{"s" if count > 1 else ""} @ {hour:%Y-%m-%d %H:00}')

        for i, monitor in enumerate(queryset):
            self.stdout.write(
                self.style.SUCCESS('✓')
                + f' {i} {monitor.monitor_type} | {monitor.name}'
            )

    def parse_hour(self, date_str):
        if not date_str:
            return now().replace(minute=0, second=0, microsecond=0)

        try:
            dt = make_aware(datetime.fromisoformat(date_str))
            return dt.replace(minute=0, second=0, microsecond=0)
        except ValueError:
            raise CommandError(f'Invalid date format: {date_str}')
