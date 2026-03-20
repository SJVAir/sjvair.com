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

    # Coverage notes:
    #
    # ZCTAs are the Census Bureau's polygon approximation of USPS ZIP codes,
    # updated every 10 years (last: 2020, next: 2030). They are the only
    # freely available source of ZIP code polygon boundaries.
    #
    # Known coverage gaps — these ZIP codes will never have a Region match:
    #
    # 1. PO Box-only ZIPs: ZCTAs are built from Census blocks and only cover
    #    geographic delivery areas. PO Box-only ZIPs (e.g. 93388, 93771,
    #    93302, 93380-93390 in Bakersfield; 93715-93793 in Fresno) have no
    #    associated land area and therefore no ZCTA polygon. No alternative
    #    free dataset covers these with geometry.
    #
    # 2. Out-of-SJV ZIPs in CEIDARS: Some CEIDARS facilities list ZIP codes
    #    outside the SJV entirely (Bay Area, Southern CA, out-of-state). These
    #    are CEIDARS data entry errors and are intentionally excluded.
    #
    # The HUD USPS ZIP-to-county crosswalk (quarterly) covers all ZIPs
    # including PO Boxes, but is tabular only — no geometry. It cannot be
    # used to create Region polygons but could supplement county-level
    # lookups if needed in the future.

    def handle(self, *args, **options):
        print('\n--- Importing Zipcodes ---')

        print('\nLoading dataset...')
        print(f'-> {DATASET_URL}')
        gdf = geodata.gdf_from_url(DATASET_URL, verify=False, limit_to_region=True, threshold=0.01)
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
