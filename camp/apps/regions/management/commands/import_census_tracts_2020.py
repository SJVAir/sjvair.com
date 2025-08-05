import math

from django.core.management.base import BaseCommand
from django.db import transaction

import pandas as pd

from camp.apps.regions.models import Region
from camp.utils import geodata
from camp.utils.gis import to_multipolygon

DATASET_URL = 'https://www2.census.gov/geo/tiger/TIGER2020/TRACT/tl_2020_06_tract.zip'
RUCA_URL = 'https://ers.usda.gov/sites/default/files/_laserfiche/DataFiles/53241/RUCA-codes-2020-tract.csv?v=27807'


def clean_json_metadata(obj):
    """
    Recursively replaces all float('nan') with None to ensure JSON compatibility.
    """
    if isinstance(obj, dict):
        return {k: clean_json_metadata(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [clean_json_metadata(v) for v in obj]
    elif isinstance(obj, float) and math.isnan(obj):
        return None
    return obj


class Command(BaseCommand):
    help = 'Import Census Tracts for the San Joaquin Valley'

    def handle(self, *args, **options):
        print('\n--- Importing Census Tracts (2020) ---')
        # Load the data and filter by tracts that are atleast 50% inside the counties
        print('\nLoading dataset...')
        print(f'-> {DATASET_URL}')
        gdf = geodata.gdf_from_zip(DATASET_URL, verify=False, limit_to_counties=True)

        print('\nLoading Rural/Urban Communting Areas...')
        print(f'-> {RUCA_URL}')
        ruca = pd.read_csv(RUCA_URL,
            dtype={'TractFIPS20': str},
            encoding='windows-1252'
        )
        ruca['TractFIPS20'] = ruca['TractFIPS20'].str.zfill(11)
        gdf = gdf.merge(ruca, left_on='GEOID', right_on='TractFIPS20', how='left')

        with transaction.atomic():
            for _, row in gdf.iterrows():
                region, created = Region.objects.import_or_update(
                    name=row.GEOID,
                    slug=row.GEOID,
                    type=Region.Type.TRACT,
                    external_id=row.GEOID,
                    version='2020',
                    geometry=to_multipolygon(row.geometry),
                    metadata=clean_json_metadata({
                        'geoid': row.GEOID,
                        'statefp': row.STATEFP,
                        'countyfp': row.COUNTYFP,
                        'tractce': row.TRACTCE,
                        'name': row.NAME,
                        'namelsad': row.NAMELSAD,
                        'aland': row.ALAND,
                        'awater': row.AWATER,
                        'ruca': {
                            'code': int(row.PrimaryRUCA) if pd.notnull(row.PrimaryRUCA) else None,
                            'description': row.PrimaryRUCADescription,
                            'urban_core': bool(row.UrbanCore) if pd.notnull(row.UrbanCore) else None,
                            'urban_core_type': row.UrbanCoreType,
                            'urban_area_code': int(row.UrbanAreaCode20) if pd.notnull(row.UrbanAreaCode20) else None,
                            'urban_area_name': row.UrbanAreaName20,
                            'primary_destination_code': int(row.PrimaryDestinationCode) if pd.notnull(row.PrimaryDestinationCode) else None,
                            'primary_destination_name': row.PrimaryDestinationName,
                        }
                    })
                )

                self.stdout.write(f'{region.get_type_display()} {"Imported" if created else "Updated"}: {region.name}')
