from django.core.management.base import BaseCommand, CommandError

from camp.apps.monitors.tasks import check_monitor_status


class Command(BaseCommand):
    help = 'Check for newly inactive monitors'

    def handle(self, *args, **options):
        check_monitor_status.call_local()
