import tempfile
import requests
import geopandas as gpd

from django.core.management.base import BaseCommand
from django.db import transaction

from camp.apps.regions.models import Region
from camp.utils.gis import to_multipolygon

# TIGER/Line ZIP Code Tabulation Areas (ZCTAs) for California (state FIPS = 06)
DATASET_URL = "https://www2.census.gov/geo/tiger/TIGER2020/ZCTA5/tl_2020_us_zcta510.zip"


class Command(BaseCommand):
    help = 'Import ZIP Code Tabulation Areas (ZCTAs) into Region table, limited to SJV counties'

    def handle(self, *args, **options):
        Region.objects.filter(type=Region.Type.ZIPCODE).delete()

        self.stdout.write('Downloading TIGER ZCTA shapefile...')
        with tempfile.NamedTemporaryFile(suffix='.zip') as tmpfile:
            try:
                response = requests.get(DATASET_URL, verify=False)
                response.raise_for_status()
            except requests.RequestException as e:
                self.stderr.write(f'❌ Failed to download county shapefile: {e}')
                return

            tmpfile.write(response.content)
            tmpfile.flush()

            gdf = gpd.read_file(f'zip://{tmpfile.name}').to_crs('EPSG:4326')

            # Load counties to clip/intersect ZIPs to the SJV region
            counties_gdf = Region.objects.filter(type=Region.Type.COUNTY).to_dataframe()
            gdf = gdf[gdf.geometry.intersects(counties_gdf.unary_union)].copy()

            with transaction.atomic():
                for _, row in gdf.iterrows():
                    zip_code = str(row['ZCTA5CE10']).zfill(5)
                    region = Region.objects.create(
                        name=zip_code,
                        slug=zip_code,
                        type=Region.Type.ZIPCODE,
                        geometry=to_multipolygon(row.geometry),
                        metadata={}
                    )
                    self.stdout.write(f'Imported ZIP: {region.name}')
