from django.core.management.base import BaseCommand, CommandError

from camp.apps.monitors.aqview.tasks import import_aqview_data


class Command(BaseCommand):
    help = 'Check for newly inactive monitors'

    def handle(self, *args, **options):
        import_aqview_data.call_local()
