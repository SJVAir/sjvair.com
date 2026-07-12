from django.core.management.base import BaseCommand

from camp.apps.forecasts.tasks import fetch_forecasts


class Command(BaseCommand):
    help = 'Fetch the SJVAPCD daily air quality forecast feed.'

    def handle(self, *args, **options):
        self.stdout.write('Fetching SJVAPCD forecasts...')
        fetch_forecasts.call_local()
        self.stdout.write(self.style.SUCCESS('Done.'))
