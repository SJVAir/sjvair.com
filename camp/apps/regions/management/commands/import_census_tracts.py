from django.core.management.base import BaseCommand
from django.db import transaction

from camp.apps.regions.models import Region, Boundary
from camp.utils import geodata
from camp.utils.gis import to_multipolygon

DATASET_URL = "https://www2.census.gov/geo/tiger/TIGER2020/TRACT/tl_2020_06_tract.zip"


class Command(BaseCommand):
    help = 'Import 2020 Census Tracts for San Joaquin Valley into the Region table'

    def handle(self, *args, **options):
        counties_gdf = Region.objects.filter(type=Region.Type.COUNTY).to_dataframe()
        gdf = geodata.gdf_from_zip(DATASET_URL, verify=False)
        gdf = gdf[gdf.geometry.intersects(counties_gdf.unary_union)].copy()

        with transaction.atomic():
            for _, row in gdf.iterrows():
                region, created = Region.objects.update_or_create(
                    external_id=row['GEOID'],
                    type=Region.Type.TRACT,
                    defaults={
                        'name': row['GEOID'],
                        'slug': row['GEOID'],
                    }
                )

                boundary, created = Boundary.objects.update_or_create(
                    region_id=region.pk,
                    version='2020',
                    defaults={
                        'geometry': to_multipolygon(row.geometry),
                        'metadata': {
                            'geoid': row['GEOID'],
                            'countyfp': row['COUNTYFP'],
                            'namelsad': row.get('NAMELSAD', ''),
                            'statefp': row.get('STATEFP', '06'),
                        }
                    }
                )

                region.boundary = boundary
                region.save()

                self.stdout.write(f'{region.get_type_display()} {"Imported" if created else "Updated"}: {region.name}')
