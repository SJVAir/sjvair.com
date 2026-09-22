from datetime import datetime

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from camp.apps.hms.tasks import fetch_fire, fetch_smoke, import_hms_range


def parse_date(s):
    return datetime.strptime(s, '%Y-%m-%d').date()


class Command(BaseCommand):
    help = (
        'Import HMS smoke and/or fire data for a single date (defaults to today) '
        'or, with --start/--end, sequentially for every date in the range.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            'date',
            nargs='?',
            type=parse_date,
            default=None,
            help='Date to import (YYYY-MM-DD). Defaults to today. Ignored when --start/--end are given.',
        )
        parser.add_argument('--start', type=parse_date, help='First date of a range to import (YYYY-MM-DD).')
        parser.add_argument('--end', type=parse_date, help='Last date of a range to import (YYYY-MM-DD).')
        parser.add_argument(
            '--delay', type=float, default=0.5,
            help='Seconds to pause between downloads when importing a range (default: 0.5).',
        )
        parser.add_argument(
            '--queue', action='store_true',
            help='Enqueue the range import on the secondary Huey queue instead of running it inline.',
        )
        parser.add_argument('--smoke', action='store_true', help='Import smoke only.')
        parser.add_argument('--fire', action='store_true', help='Import fire only.')

    def handle(self, *args, **options):
        # If neither flag is set, import both.
        do_smoke = options['smoke'] or not options['fire']
        do_fire = options['fire'] or not options['smoke']

        if bool(options['start']) != bool(options['end']):
            raise CommandError('--start and --end must be given together.')

        if options['start']:
            return self.handle_range(options['start'], options['end'], do_smoke, do_fire, options)

        date = options['date'] or timezone.now().astimezone(settings.DEFAULT_TIMEZONE).date()

        if do_smoke:
            self.stdout.write(f'Importing HMS smoke for {date}...')
            fetch_smoke.call_local(date)
            self.stdout.write(self.style.SUCCESS('Smoke done.'))

        if do_fire:
            self.stdout.write(f'Importing HMS fire for {date}...')
            fetch_fire.call_local(date)
            self.stdout.write(self.style.SUCCESS('Fire done.'))

    def handle_range(self, start, end, do_smoke, do_fire, options):
        kwargs = dict(smoke=do_smoke, fire=do_fire, delay=options['delay'])
        what = ' and '.join(name for name, on in (('smoke', do_smoke), ('fire', do_fire)) if on)

        if options['queue']:
            import_hms_range(start, end, **kwargs)
            self.stdout.write(self.style.SUCCESS(f'Queued HMS {what} import for {start} to {end}.'))
            return

        self.stdout.write(f'Importing HMS {what} for {start} to {end}...')
        result = import_hms_range.call_local(start, end, **kwargs)
        for item in result['skipped']:
            self.stdout.write(self.style.WARNING(f'Skipped (not in NOAA archive): {item}'))
        self.stdout.write(self.style.SUCCESS('Done.'))
