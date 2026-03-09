from datetime import datetime

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from camp.apps.hms.tasks import fetch_fire, fetch_smoke


class Command(BaseCommand):
    help = 'Import HMS smoke and/or fire data for a given date (defaults to today).'

    def add_arguments(self, parser):
        parser.add_argument(
            'date',
            nargs='?',
            type=lambda s: datetime.strptime(s, '%Y-%m-%d').date(),
            default=None,
            help='Date to import (YYYY-MM-DD). Defaults to today.',
        )
        parser.add_argument('--smoke', action='store_true', help='Import smoke only.')
        parser.add_argument('--fire', action='store_true', help='Import fire only.')

    def handle(self, *args, **options):
        date = options['date'] or timezone.now().astimezone(settings.DEFAULT_TIMEZONE).date()

        # If neither flag is set, import both.
        do_smoke = options['smoke'] or not options['fire']
        do_fire = options['fire'] or not options['smoke']

        if do_smoke:
            self.stdout.write(f'Importing HMS smoke for {date}...')
            fetch_smoke.call_local(date)
            self.stdout.write(self.style.SUCCESS('Smoke done.'))

        if do_fire:
            self.stdout.write(f'Importing HMS fire for {date}...')
            fetch_fire.call_local(date)
            self.stdout.write(self.style.SUCCESS('Fire done.'))
