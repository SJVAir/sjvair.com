from django.core.management.base import BaseCommand
from huey.contrib.djhuey import HUEY


class Command(BaseCommand):
    def handle(self, *args, **kwargs):
        HUEY.pending_count()
        HUEY.flush()
