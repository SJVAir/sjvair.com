from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from camp.apps.regions.models import Region
from camp.utils import geodata
from camp.utils.gis import to_multipolygon

# CLASSFP: https://www.census.gov/library/reference/code-lists/class-codes.html


class Command(BaseCommand):
    help = 'Import California cities (places) into the Region table (limited to those within SJV counties)'

    def handle(self, *args, **options):
        print('\n--- Importing Cities / CDPs ---')
        gdf = geodata.gdf_from_ckan('ca-geographic-boundaries',
            resource_name='CA Places Boundaries',
            limit_to_counties=True
        )

        with transaction.atomic():
            for _, row in gdf.iterrows():
                if row.CLASSFP == 'C1':
                    region_type = Region.Type.CITY
                elif row.CLASSFP in {'U1', 'U2'}:
                    region_type = Region.Type.CDP
                else:
                    continue

                region, created = Region.objects.import_or_update(
                    name=row.NAME,
                    slug=slugify(row.NAME),
                    type=region_type,
                    external_id=row.GEOID,
                    version='2023',
                    geometry=to_multipolygon(row.geometry),
                    metadata={
                        'geoid': row.GEOID,
                        'statefp': row.STATEFP,
                        'placefp': row.PLACEFP,
                        'name': row.NAME,
                        'namelsad': row.NAMELSAD,
                        'aland': row.ALAND,
                        'awater': row.AWATER,
                    }
                )

                self.stdout.write(f'{region.get_type_display()} {"Imported" if created else "Updated"}: {region.name}')
