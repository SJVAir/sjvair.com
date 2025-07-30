from django.core.management.base import BaseCommand
from django.db import transaction

from camp.apps.regions.models import Region, Boundary
from camp.utils import geodata
from camp.utils.gis import to_multipolygon

DATASET_URL = "https://www2.census.gov/geo/tiger/TIGER2020/ZCTA5/tl_2020_us_zcta510.zip"


class Command(BaseCommand):
    help = 'Import ZIP Code Tabulation Areas (ZCTAs) into Region table, limited to SJV counties'

    def handle(self, *args, **options):
        counties_gdf = Region.objects.filter(type=Region.Type.COUNTY).to_dataframe()
        gdf = geodata.gdf_from_zip(DATASET_URL, verify=False)
        gdf = gdf[gdf.geometry.intersects(counties_gdf.unary_union)].copy()

        with transaction.atomic():
            for _, row in gdf.iterrows():
                zip_code = str(row['ZCTA5CE10']).zfill(5)
                region, created = Region.objects.update_or_create(
                    external_id=zip_code,
                    type=Region.Type.ZIPCODE,
                    defaults={
                        'name': zip_code,
                        'slug': zip_code,
                    }
                )

                boundary, created = Boundary.objects.update_or_create(
                    region_id=region.pk,
                    version='2020',
                    defaults={
                        'geometry': to_multipolygon(row.geometry),
                        'metadata': {}
                    }
                )

                region.boundary = boundary
                region.save()

                self.stdout.write(f'{region.get_type_display()} {"Imported" if created else "Updated"}: {region.name}')
