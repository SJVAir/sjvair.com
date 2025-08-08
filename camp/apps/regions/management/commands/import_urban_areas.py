from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from camp.apps.regions.models import Region
from camp.utils import geodata
from camp.utils.gis import to_multipolygon

DATASET_URL = "https://www2.census.gov/geo/tiger/TIGER2010/TRACT/2010/tl_2010_06_tract10.zip"


class Command(BaseCommand):
    help = 'Import Census Tracts for the San Joaquin Valley'

    def handle(self, *args, **options):
        print('\n--- Importing Urban Areas ---')
        gdf = geodata.gdf_from_ckan('2020-adjusted-urban-area', limit_to_counties=True)

        with transaction.atomic():
            for _, row in gdf.iterrows():
                name = row.NAME
                if name.endswith(', CA'):
                    name = name[:-4]
                region, created = Region.objects.import_or_update(
                    name=name,
                    slug=slugify(name),
                    type=Region.Type.URBAN_AREA,
                    external_id=row.UACE20,
                    version='2020',
                    geometry=to_multipolygon(row.geometry),
                    metadata={
                        'uace10': row.UACE10,
                        'uace20': row.UACE20,
                        'population': row.Population,
                        'area_sqm': row.Area_sqm,
                        'urban_area_type': 'urbanized' if row.UrbanAreas == 2 else 'small_urban',
                        'urban_area_code': row.UrbanAreas
                    }
                )

                self.stdout.write(f'{region.get_type_display()} {"Imported" if created else "Updated"}: {region.name}')
