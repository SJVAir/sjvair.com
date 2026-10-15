from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from camp.apps.regions import population
from camp.apps.regions.models import Region


class Command(BaseCommand):
    help = (
        "Load ACS 5-year total population (B01003) into Region.metadata['population'] "
        'for counties, ZIP areas, 2020 census tracts, cities, CDPs and school districts. '
        'AB 617 communities have no Census geography and get none. Requires a (free) Census API '
        'key set as CENSUS_API_KEY. Safe to re-run; re-run when a new ACS 5-year '
        'release lands.'
    )

    def add_arguments(self, parser):
        parser.add_argument('--year', type=int, default=population.ACS_YEAR, help='ACS 5-year release (end year)')

    def handle(self, *args, **options):
        for geography, (region_types, _, _) in population.GEOGRAPHIES.items():
            try:
                counts = population.fetch(geography, options['year'], key=settings.CENSUS_API_KEY)
            except population.CensusAPIError as error:
                raise CommandError(str(error))
            updated, missing = population.apply(region_types, counts)
            self.stdout.write(f'{geography}: {updated} updated, {missing} not in the ACS')
        try:
            counts = population.fetch_school_districts(options['year'], key=settings.CENSUS_API_KEY)
        except population.CensusAPIError as error:
            raise CommandError(str(error))
        updated, missing = population.apply(Region.Type.SCHOOL_DISTRICT, counts, geoid=population.fed_id)
        self.stdout.write(f'school districts: {updated} updated, {missing} not in the ACS')
