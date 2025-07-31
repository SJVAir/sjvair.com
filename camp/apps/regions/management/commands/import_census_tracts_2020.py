from django.core.management.base import BaseCommand
from django.db import transaction

from camp.apps.regions.models import Region
from camp.utils import geodata
from camp.utils.gis import to_multipolygon

DATASET_URL = "https://www2.census.gov/geo/tiger/TIGER2020/TRACT/tl_2020_06_tract.zip"


class Command(BaseCommand):
    help = 'Import Census Tracts for the San Joaquin Valley'

    def handle(self, *args, **options):
        counties_gdf = Region.objects.filter(type=Region.Type.COUNTY).to_dataframe()
        gdf = geodata.gdf_from_zip(DATASET_URL, verify=False)
        gdf = gdf[gdf.geometry.intersects(counties_gdf.unary_union)].copy()

        with transaction.atomic():
            for _, row in gdf.iterrows():
                region, created = Region.objects.import_or_update(
                    name=row['GEOID'],
                    slug=row['GEOID'],
                    type=Region.Type.TRACT,
                    external_id=row['GEOID'],
                    version='2020',
                    geometry=to_multipolygon(row.geometry),
                    metadata={
                        'geoid': row['GEOID'],
                        'statefp': row['STATEFP'],
                        'countyfp': row['COUNTYFP'],
                        'tractce': row['TRACTCE'],
                        'name': row['NAME'],
                        'namelsad': row['NAMELSAD'],
                        'aland': row['ALAND'],
                        'awater': row['AWATER'],
                    }
                )

                self.stdout.write(f'{region.get_type_display()} {"Imported" if created else "Updated"}: {region.name}')
