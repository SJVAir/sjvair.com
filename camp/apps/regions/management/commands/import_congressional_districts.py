from django.core.management.base import BaseCommand
from django.db import transaction

from camp.apps.regions.models import Region, Boundary
from camp.utils import geodata
from camp.utils.gis import to_multipolygon

DATASET_URL = 'https://www2.census.gov/geo/tiger/TIGER2022/CD/tl_2022_06_cd118.zip'


class Command(BaseCommand):
    help = 'Import 116th Congressional Districts (2020) that intersect with San Joaquin Valley counties.'

    def handle(self, *args, **options):
        counties_gdf = Region.objects.filter(type=Region.Type.COUNTY).to_dataframe()
        gdf = geodata.gdf_from_zip(DATASET_URL, verify=False)
        gdf = gdf[gdf.geometry.intersects(counties_gdf.unary_union)].copy()

        with transaction.atomic():
            for _, row in gdf.iterrows():
                region, created = Region.objects.update_or_create(
                    external_id=row['GEOID20'],
                    type=Region.Type.CONGRESSIONAL_DISTRICT,
                    defaults={
                        'name': row['NAMELSAD20'],
                        'slug': f'cd-{row["CD118FP"]}',
                    }
                )

                boundary, created = Boundary.objects.update_or_create(
                    region_id=region.pk,
                    version='2022',
                    defaults={
                        'geometry': to_multipolygon(row.geometry),
                        'metadata': {
                            'statefp': row['STATEFP20'],  # FIPS code for California ('06')
                            'geoid': row['GEOID20'],  # Unique geographic identifier for the district (e.g., '0603')
                            'cd_number': row['CD118FP'],  # District number within the 118th Congress (e.g., '03')
                            'name': row['NAMELSAD20'],  # Full label (e.g., 'Congressional District 3')
                            'lsad': row['LSAD20'],  # Legal/Statistical Area Description code (e.g., 'C2')
                            'session': row['CDSESSN'],  # Congressional session number (should be 118)
                            'aland': row['ALAND20'],  # Land area in square meters
                            'awater': row['AWATER20'],  # Water area in square meters
                        },
                    }
                )

                region.boundary = boundary
                region.save()

                self.stdout.write(f'{region.get_type_display()} {"Imported" if created else "Updated"}: {region.name}')
