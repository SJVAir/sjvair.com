import calendar
import re

from datetime import date, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from camp.apps.archive.models import EntryArchive
from camp.apps.monitors.models import Monitor


class Command(BaseCommand):
    help = 'Create entry archives'

    month_re = re.compile(r'^(\d{4})-(1[0-2]|0?[1-9])$')

    def add_arguments(self, parser):
        parser.add_argument('-d', '--date', type=str)
        parser.add_argument('-m', '--monitor', type=str)

    def get_year_month(self, value):
        if value is None:
            # Use the previous month
            value = timezone.now().date().replace(day=1) - timedelta(hours=24)
            return (value.year, value.month)

        # Parse and validate the supplied month
        match = self.month_re.match(value)
        if match is not None:
            return [int(x) for x in match.groups()]
        raise CommandError('')

    def get_monitor_list(self, monitor_id=None):
        monitors = Monitor.objects.all()
        if monitor_id is not None:
            monitors = monitors.filter(pk=monitor_id)
        return monitors

    def handle(self, *args, **options):
        year, month = self.get_year_month(options.get('month'))
        monitor_list = self.get_monitor_list(options.get('monitor'))

        for monitor in monitor_list:
            print(monitor.name)
            try:
                archive = EntryArchive.objects.get(monitor_id=monitor.pk, year=year, month=month)
            except EntryArchive.DoesNotExist:
                archive = EntryArchive(monitor=monitor, year=year, month=month)
            archive.generate()
            archive.save()
            print(f'\t{archive.data.url}')
