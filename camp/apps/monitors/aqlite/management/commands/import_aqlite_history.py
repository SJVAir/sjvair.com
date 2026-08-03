from datetime import datetime

from django.core.management.base import BaseCommand, CommandError

from camp.apps.monitors.aqlite.tasks import import_history


class Command(BaseCommand):
    help = 'Import historical AQLite data and run the O3 pipeline (RAW → CLEANED → CALIBRATED)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--start',
            type=str,
            default=None,
            help='Start date YYYY-MM-DD in local time (default: 7 days ago)',
        )
        parser.add_argument(
            '--end',
            type=str,
            default=None,
            help='End date YYYY-MM-DD in local time (default: now)',
        )
        parser.add_argument(
            '--device-id',
            type=str,
            action='append',
            dest='device_ids',
            metavar='DEVICE_ID',
            help='Limit to a specific device ID, e.g. AQLite-1608 (repeatable)',
        )
        parser.add_argument(
            '--local',
            action='store_true',
            help='Run synchronously via call_local() instead of enqueueing.',
        )

    def handle(self, *args, **options):
        for key in ('start', 'end'):
            if options[key]:
                try:
                    datetime.strptime(options[key], '%Y-%m-%d')
                except ValueError:
                    raise CommandError('Dates must be in YYYY-MM-DD format.')

        kwargs = dict(
            start=options['start'],
            end=options['end'],
            device_ids=options['device_ids'],
        )

        if options['local']:
            import_history.call_local(**kwargs)
        else:
            import_history(**kwargs)
