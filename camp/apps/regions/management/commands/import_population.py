from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from camp.apps.regions import population


class Command(BaseCommand):
    help = (
        "Load ACS 5-year total population (B01003) into Region.metadata['population'] "
        'for counties, ZIP areas and 2020 census tracts. Requires a (free) Census API '
        'key set as CENSUS_API_KEY. Safe to re-run; re-run when a new ACS 5-year '
        'release lands.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--year', type=int, default=population.ACS_YEAR, help='ACS 5-year release (end year)')

    def handle(self, *args, **options):
        for geography, (region_type, _, _) in population.GEOGRAPHIES.items():
            try:
                counts = population.fetch(geography, options['year'], key=settings.CENSUS_API_KEY)
            except population.CensusAPIError as error:
                raise CommandError(str(error))
            updated, missing = population.apply(region_type, counts)
            self.stdout.write(f'{geography}: {updated} updated, {missing} not in the ACS')
