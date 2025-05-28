from django.core.management.base import BaseCommand
from django_q.models import Schedule

"""
   This script is used to delete scheduler objects in order to create a new one.
   This is specifically to apply changes to the data retrieval scheduler. 
"""


class Command(BaseCommand):
    help = "Clear all django-q scheduled tasks"

    def handle(self, *args, **kwargs):
        count, _ = Schedule.objects.all().delete()
        self.stdout.write(f"Deleted {count} scheduled tasks")