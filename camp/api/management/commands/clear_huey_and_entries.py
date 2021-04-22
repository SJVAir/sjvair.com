from django.core.management.base import BaseCommand
from huey.contrib.djhuey import HUEY

from camp.apps.monitors.models import Entry

class Command(BaseCommand):
    def handle(self, *args, **kwargs):
        HUEY.pending_count()
        HUEY.flush()
        Entry.objects.all().delete()
