from django.core.management.base import BaseCommand

from camp.apps.integrate.ces4.data import Ces4Data
from camp.apps.integrate.ces4.models import Tract

class Command(BaseCommand):
    def handle(self, *args, **options):
        Tract.objects.all().delete()
        Ces4Data.ces4_request()