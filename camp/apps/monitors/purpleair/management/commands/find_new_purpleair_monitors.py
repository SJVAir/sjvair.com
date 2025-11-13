from django.core.management.base import BaseCommand
from camp.apps.monitors.purpleair.tasks import find_new_monitors


class Command(BaseCommand):
    def handle(self, *args, **kwargs):
        find_new_monitors.call_local()
