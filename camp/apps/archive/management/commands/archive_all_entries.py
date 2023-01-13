from datetime import date, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from camp.apps.archive.models import EntryArchive
from camp.apps.archive.tasks import create_entry_archive
from camp.apps.monitors.models import Monitor, Entry


class Command(BaseCommand):
    help = 'Create entry archives'
    today = timezone.now().date()

    def add_arguments(self, parser):
        parser.add_argument('-m', '--monitor', type=str)

    def get_monitor_list(self, monitor_id=None):
        monitors = Monitor.objects.all()
        if monitor_id is not None:
            monitors = monitors.filter(pk=monitor_id)
        return monitors

    def get_months(self, monitor):
        try:
            entry = monitor.entries.earliest('timestamp')
        except Entry.DoesNotExist:
            return

        initial = date(entry.timestamp.year, entry.timestamp.month, 1) - timedelta(days=1)
        year = initial.year
        month = initial.month

        while True:
            # Calculate the next month
            month += 1
            if month == 13:
                year += 1
                month = 1

            # Kill it when we've reached the current month.
            if year >= self.today.year and month >= self.today.month:
                break

            yield year, month

    def handle(self, *args, **options):
        monitor_list = self.get_monitor_list(options.get('monitor'))

        for monitor in monitor_list:
            print(f'{monitor.name}')
            for year, month in self.get_months(monitor):
                if monitor.archives.filter(year=year, month=month).exists():
                    print(f' X {year}-{month}')
                    continue
                print(f' - {year}-{month}')
                create_entry_archive(monitor.pk, year, month)
