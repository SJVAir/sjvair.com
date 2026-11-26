from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError

from camp.apps.monitors.cimis.models import CIMIS
from camp.apps.monitors.cimis.restamp import ShortAnswer, restamp_station


class Command(BaseCommand):
    help = (
        "Re-pull CIMIS stations' stored history, from each station's first stored date "
        'through today (Pacific), and stamp it at the start of each hour. One transaction '
        'per station. '
        'If the live ingest writes the same hour during a run, the station aborts with '
        'nothing written; a re-run is safe.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--monitor', action='append', dest='monitors', default=[],
                            help='CIMIS monitor id (repeatable; required)')
        parser.add_argument('--dry-run', action='store_true', help='Fetch and count; write nothing')

    def handle(self, *args, **options):
        if not options['monitors']:
            raise CommandError('--monitor is required (one or more CIMIS monitor ids).')

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
                result = restamp_station(monitor, dry_run=dry_run)
            except ShortAnswer as error:
                failed.append(str(monitor.pk))
                self.stderr.write(self.style.ERROR(f'  aborted: {error}'))
                continue
            except Exception as error:
                failed.append(str(monitor.pk))
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
            self.stdout.write(f'  malformed records skipped: {result.skipped}')

        if failed:
            raise CommandError(f'Failed for: {", ".join(failed)}')
