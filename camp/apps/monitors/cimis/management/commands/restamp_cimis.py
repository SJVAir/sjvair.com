from datetime import date

from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from camp.apps.monitors.cimis.models import CIMIS
from camp.apps.monitors.cimis.restamp import restamp_station
from camp.utils.datetime import localtime


class Command(BaseCommand):
    help = (
        "Re-pull CIMIS stations' stored history, from each station's first stored date "
        'to --end, and stamp it at the start of each hour. One transaction per station.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--monitor', action='append', dest='monitors', default=[],
                            help='CIMIS monitor id (repeatable; required)')
        parser.add_argument('--end', type=str, help='Last date YYYY-MM-DD (inclusive; default today, Pacific)')
        parser.add_argument('--dry-run', action='store_true', help='Fetch and count; write nothing')

    def handle(self, *args, **options):
        if not options['monitors']:
            raise CommandError('--monitor is required (one or more CIMIS monitor ids).')

        if options['end']:
            try:
                end = date.fromisoformat(options['end'])
            except ValueError:
                raise CommandError('--end must be in YYYY-MM-DD format.')
        else:
            end = localtime().date()

        monitors = []
        for monitor_id in options['monitors']:
            try:
                monitors.append(CIMIS.objects.get(pk=monitor_id))
            except (CIMIS.DoesNotExist, ValidationError, ValueError):
                raise CommandError(f'No CIMIS monitor with id {monitor_id!r}.')

        dry_run = options['dry_run']
        if dry_run:
            self.stdout.write('Dry run: nothing will be written.')

        failed = []
        for monitor in monitors:
            self.stdout.write(f'{monitor.name} ({monitor.pk})')
            try:
                result = restamp_station(monitor, end=end, dry_run=dry_run)
            except Exception as error:
                failed.append(monitor.pk)
                self.stderr.write(self.style.ERROR(f'  failed, nothing written: {error!r}'))
                continue

            if result.start is None:
                self.stdout.write('  nothing stored')
                continue

            self.stdout.write(f'  first stored date: {result.start}')
            self.stdout.write(f'  end: {result.end}')
            self.stdout.write(f'  labels fetched: {result.labels}')
            self.stdout.write('  rows in the window:')
            for entry_type, count in result.deleted_by_type.items():
                self.stdout.write(f'    {entry_type}: {count}')
            self.stdout.write(f'  rows in the window, total: {result.deleted}')
            self.stdout.write(f'  rows written: {result.written}')

        if failed:
            raise CommandError(f'Failed for: {", ".join(failed)}')
