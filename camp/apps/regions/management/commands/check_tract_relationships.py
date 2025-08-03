import tempfile
from pathlib import Path

import pandas as pd
import requests

from django.core.management.base import BaseCommand

from camp.apps.regions.models import Region

RELATIONSHIP_URL = 'https://www2.census.gov/geo/docs/maps-data/data/rel2020/tract/tab20_tract20_tract10_natl.txt'
CACHE_PATH = Path(f'{tempfile.tempdir}/tract_2010_2020_relationship.txt')


class Command(BaseCommand):
    help = 'Compare unmatched 2010/2020 tracts against census relationship file'

    def add_arguments(self, parser):
        parser.add_argument('--refresh', action='store_true', help='Re-download relationship file')

    def handle(self, *args, **options):
        if options['refresh'] or not CACHE_PATH.exists():
            self.stdout.write('Downloading relationship file...')
            response = requests.get(RELATIONSHIP_URL, verify=False)
            response.raise_for_status()
            CACHE_PATH.write_text(response.text)
        else:
            self.stdout.write(f'Using cached file at {CACHE_PATH}')

        df = pd.read_csv(CACHE_PATH, dtype=str, sep='|')
        self.stdout.write(f'Loaded {len(df):,} rows from relationship file\n')

        fips = {
            r.boundary.metadata['statefp'] + r.boundary.metadata['countyfp']
            for r in Region.objects.filter(type=Region.Type.COUNTY)
        }

        df['FIPS_TRACT_10'] = df['GEOID_TRACT_10'].str[:5]
        df['FIPS_TRACT_20'] = df['GEOID_TRACT_20'].str[:5]
        df = df[df['FIPS_TRACT_10'].isin(fips) | df['FIPS_TRACT_20'].isin(fips)]
        self.stdout.write(f'{len(df):,} rows for California tracts\n')

        # Sets of GEOIDs in rel file
        rel_10 = set(df['GEOID_TRACT_10'])
        rel_20 = set(df['GEOID_TRACT_20'])

        # Only-2010 and Only-2020 tracts
        only_2010 = Region.objects.filter(
            type=Region.Type.TRACT,
            boundaries__version='2010'
        ).exclude(
            boundaries__version='2020'
        )

        only_2020 = Region.objects.filter(
            type=Region.Type.TRACT,
            boundaries__version='2020'
        ).exclude(
            boundaries__version='2010'
        )

        only_2010_geoids = set(only_2010.values_list('external_id', flat=True))
        only_2020_geoids = set(only_2020.values_list('external_id', flat=True))

        # Compare against rel file
        missing_2010 = only_2010_geoids - rel_10
        missing_2020 = only_2020_geoids - rel_20

        print(f'Only in 2010: {len(only_2010_geoids)}')
        print(f'  - Not found in rel file: {len(missing_2010)}')
        print(f'Only in 2020: {len(only_2020_geoids)}')
        print(f'  - Not found in rel file: {len(missing_2020)}')

        if missing_2010:
            print('\nOnly-2010 tracts NOT in rel file:')
            for geoid in sorted(missing_2010):
                print(f'  - {geoid}')

        if missing_2020:
            print('\nOnly-2020 tracts NOT in rel file:')
            for geoid in sorted(missing_2020):
                print(f'  - {geoid}')
