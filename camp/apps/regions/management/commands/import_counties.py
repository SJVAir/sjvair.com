from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from camp.apps.regions.managers import SJV_COUNTIES
from camp.apps.regions.models import Region
from camp.utils import geodata
from camp.utils.gis import to_multipolygon


# CA state county codes (01–58, alphabetical order) used by CDPR, CARB, and other CA agencies.
# Not included in the CKAN geographic boundaries dataset, so stored here as a reference.
CA_COUNTY_CODES = {
    'Alameda': '01', 'Alpine': '02', 'Amador': '03', 'Butte': '04',
    'Calaveras': '05', 'Colusa': '06', 'Contra Costa': '07', 'Del Norte': '08',
    'El Dorado': '09', 'Fresno': '10', 'Glenn': '11', 'Humboldt': '12',
    'Imperial': '13', 'Inyo': '14', 'Kern': '15', 'Kings': '16',
    'Lake': '17', 'Lassen': '18', 'Los Angeles': '19', 'Madera': '20',
    'Marin': '21', 'Mariposa': '22', 'Mendocino': '23', 'Merced': '24',
    'Modoc': '25', 'Mono': '26', 'Monterey': '27', 'Napa': '28',
    'Nevada': '29', 'Orange': '30', 'Placer': '31', 'Plumas': '32',
    'Riverside': '33', 'Sacramento': '34', 'San Benito': '35', 'San Bernardino': '36',
    'San Diego': '37', 'San Francisco': '38', 'San Joaquin': '39', 'San Luis Obispo': '40',
    'San Mateo': '41', 'Santa Barbara': '42', 'Santa Clara': '43', 'Santa Cruz': '44',
    'Shasta': '45', 'Sierra': '46', 'Siskiyou': '47', 'Solano': '48',
    'Sonoma': '49', 'Stanislaus': '50', 'Sutter': '51', 'Tehama': '52',
    'Trinity': '53', 'Tulare': '54', 'Tuolumne': '55', 'Ventura': '56',
    'Yolo': '57', 'Yuba': '58',
}

class Command(BaseCommand):
    help = 'Import California counties into the Region table'

    def add_arguments(self, parser):
        parser.add_argument(
            '--county',
            action='append',
            dest='counties',
            metavar='NAME',
            help='County name(s) to import (can be used multiple times). '
                 'Defaults to SJV counties.',
        )

    def handle(self, *args, **options):
        # --county uses the short NAME form (e.g. "Los Angeles"); SJV_COUNTIES
        # uses NAMELSAD (e.g. "Fresno County") — keep them separate.
        short_names = set(options.get('counties') or [
            name.replace(' County', '') for name in SJV_COUNTIES
        ])

        print('\n--- Importing Counties ---')
        gdf = geodata.gdf_from_ckan('ca-geographic-boundaries', resource_name='CA County Boundaries')
        gdf = gdf[gdf['NAME'].isin(short_names)].copy()

        if gdf.empty:
            self.stderr.write(f'No counties found matching: {short_names}')
            return

        with transaction.atomic():
            for _, row in gdf.iterrows():
                region, created = Region.objects.import_or_update(
                    name=row.NAMELSAD,
                    slug=slugify(row.NAME),
                    type=Region.Type.COUNTY,
                    external_id=row.GEOID,
                    version='2023',
                    geometry=to_multipolygon(row.geometry),
                    metadata={
                        'ca_county_code': CA_COUNTY_CODES.get(row.NAME),
                        'geoid': row.GEOID,
                        'statefp': row.STATEFP,
                        'countyfp': row.COUNTYFP,
                        'name': row.NAME,
                        'namelsad': row.NAMELSAD,
                    },
                    boundary_metadata={
                        'aland': row.ALAND,
                        'awater': row.AWATER,
                    },
                )

                self.stdout.write(f'{region.get_type_display()} {"Imported" if created else "Updated"}: {region.name}')
