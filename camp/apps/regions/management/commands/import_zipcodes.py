from django.core.management.base import BaseCommand
from django.db import transaction

from camp.apps.regions.models import Region
from camp.utils import geodata
from camp.utils.gis import to_multipolygon

DATASET_URL = "https://www2.census.gov/geo/tiger/TIGER2020/ZCTA5/tl_2020_us_zcta510.zip"


class Command(BaseCommand):
    help = 'Import ZIP Code Tabulation Areas (ZCTAs) into Region table, limited to SJV counties'

    def handle(self, *args, **options):
        print('\n--- Importing Zipcodes ---')
        counties_gdf = Region.objects.filter(type=Region.Type.COUNTY).to_dataframe()
        gdf = geodata.gdf_from_zip(DATASET_URL, verify=False)
        gdf = geodata.filter_by_overlap(gdf, counties_gdf.unary_union, 0.25)

        with transaction.atomic():
            for _, row in gdf.iterrows():
                zip_code = str(row['ZCTA5CE10']).zfill(5)
                region, created = Region.objects.import_or_update(
                    name=zip_code,
                    slug=zip_code,
                    external_id=zip_code,
                    type=Region.Type.ZIPCODE,
                    version='2020',
                    geometry=to_multipolygon(row.geometry),
                )

                self.stdout.write(f'{region.get_type_display()} {"Imported" if created else "Updated"}: {region.name}')
