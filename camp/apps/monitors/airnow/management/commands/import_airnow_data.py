from django.core.management.base import BaseCommand, CommandError

from camp.apps.monitors.airnow.tasks import import_airnow_data, import_airnow_data_legacy


class Command(BaseCommand):
    help = 'Import data from AirNow.gov'

    def handle(self, *args, **options):
        import_airnow_data.call_local()
        import_airnow_data_legacy.call_local()
