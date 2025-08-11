from django.core.management.base import BaseCommand
from django.db import transaction

import pandas as pd

from camp.apps.regions.models import Region
from camp.utils import geodata
from camp.utils.gis import to_multipolygon

DATASET_URL = 'https://www2.census.gov/geo/tiger/TIGER2020/ZCTA5/tl_2020_us_zcta510.zip'
RUCA_URL = 'https://ers.usda.gov/sites/default/files/_laserfiche/DataFiles/53241/RUCA-codes-2020-zipcode.csv?v=33034'

class Command(BaseCommand):
    help = 'Import ZIP Code Tabulation Areas (ZCTAs) into Region table, limited to SJV counties'

    def handle(self, *args, **options):
        print('\n--- Importing Zipcodes ---')

        print('\nLoading dataset...')
        print(f'-> {DATASET_URL}')
        gdf = geodata.gdf_from_url(DATASET_URL, verify=False, limit_to_region=True, threshold=0.25)
        gdf['ZCTA5CE10'] = gdf['ZCTA5CE10'].astype(str).str.zfill(5)

        print('\nLoading Rural/Urban Communting Areas...')
        print(f'-> {RUCA_URL}')
        ruca = pd.read_csv(RUCA_URL,
            dtype={'ZIPCode': str},
            encoding='windows-1252'
        )
        ruca = ruca[ruca['State'] == 'CA']
        ruca['ZIPCode'] = ruca['ZIPCode'].astype(str).str.zfill(5)
        gdf = gdf.merge(ruca, left_on='ZCTA5CE10', right_on='ZIPCode', how='left')

        with transaction.atomic():
            for _, row in gdf.iterrows():
                zip_code = str(row.ZCTA5CE10).zfill(5)
                region, created = Region.objects.import_or_update(
                    name=zip_code,
                    slug=zip_code,
                    external_id=zip_code,
                    type=Region.Type.ZIPCODE,
                    version='2020',
                    geometry=to_multipolygon(row.geometry),
                    metadata={
                        'ruca': {
                            'primary': row.PrimaryRUCA,
                            'secondary': row.SecondaryRUCA,
                            'type': row.ZIPCodeType,
                            'post_office': row.POName,
                        }
                    }
                )

                self.stdout.write(f'{region.get_type_display()} {"Imported" if created else "Updated"}: {region.name}')
