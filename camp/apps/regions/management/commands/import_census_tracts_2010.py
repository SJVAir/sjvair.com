from django.core.management.base import BaseCommand
from django.db import transaction

from camp.apps.regions.models import Region
from camp.utils import geodata
from camp.utils.gis import to_multipolygon

DATASET_URL = "https://www2.census.gov/geo/tiger/TIGER2010/TRACT/2010/tl_2010_06_tract10.zip"


class Command(BaseCommand):
    help = 'Import Census Tracts for the San Joaquin Valley'

    def handle(self, *args, **options):
        counties_gdf = Region.objects.filter(type=Region.Type.COUNTY).to_dataframe()
        gdf = geodata.gdf_from_zip(DATASET_URL, verify=False)
        gdf = gdf[gdf.geometry.intersects(counties_gdf.unary_union)].copy()

        with transaction.atomic():
            for _, row in gdf.iterrows():
                region, created = Region.objects.import_or_update(
                    name=row['GEOID10'],
                    slug=row['GEOID10'],
                    type=Region.Type.TRACT,
                    external_id=row['GEOID10'],
                    version='2010',
                    geometry=to_multipolygon(row.geometry),
                    metadata={
                        'geoid': row['GEOID10'],
                        'statefp': row['STATEFP10'],
                        'countyfp': row['COUNTYFP10'],
                        'tractce': row['TRACTCE10'],
                        'name': row['NAME10'],
                        'namelsad': row['NAMELSAD10'],
                        'aland': row['ALAND10'],
                        'awater': row['AWATER10']
                    }
                )

                self.stdout.write(f'{region.get_type_display()} {"Imported" if created else "Updated"}: {region.name}')
