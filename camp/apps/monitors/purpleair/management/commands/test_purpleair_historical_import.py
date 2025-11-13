from datetime import date

from django.core.management.base import BaseCommand

from camp.apps.entries.models import BaseEntry
from camp.apps.monitors.purpleair.models import PurpleAir
from camp.apps.monitors.purpleair.tasks import import_monitor_history


class Command(BaseCommand):
    def handle(self, *args, **kwargs):
        monitor = PurpleAir.objects.get(sensor_id=8892)
        start_date = date(2024, 1, 1)
        end_date = date(2024, 12, 31)

        print('Deleting existing entries...')
        for EntryModel in BaseEntry.get_subclasses():
            EntryModel.objects.filter(
                monitor_id=monitor.pk,
                timestamp__date__range=(start_date, end_date),
            ).delete()

        print('Importing history...')
        import_monitor_history.call_local(
            monitor_id=monitor.pk,
            start_date=start_date,
            end_date=end_date,
        )
