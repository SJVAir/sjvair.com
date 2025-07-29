import tempfile
import requests
import geopandas as gpd

from django.core.management.base import BaseCommand
from django.db import transaction

from camp.apps.regions.models import Region
from camp.utils.gis import to_multipolygon

DATASET_URL = "https://www2.census.gov/geo/tiger/TIGER2020/TRACT/tl_2020_06_tract.zip"

SJV_COUNTIES = {
    '019': 'Fresno',
    '029': 'Kern',
    '031': 'Kings',
    '039': 'Madera',
    '047': 'Merced',
    '077': 'San Joaquin',
    '099': 'Stanislaus',
    '107': 'Tulare',
}


class Command(BaseCommand):
    help = 'Import 2020 Census Tracts for San Joaquin Valley into the Region table'

    def handle(self, *args, **options):
        with tempfile.NamedTemporaryFile(suffix='.zip') as tmpfile:
            self.stdout.write('Downloading 2020 Census Tracts ZIP...')
            try:
                r = requests.get(DATASET_URL, verify=False)
                r.raise_for_status()
            except requests.RequestException as e:
                self.stderr.write(f'❌ Failed to download census tract shapefile: {e}')
                return

            tmpfile.write(r.content)
            tmpfile.flush()

            counties_gdf = Region.objects.filter(type=Region.Type.COUNTY).to_dataframe()
            gdf = gpd.read_file(f'zip://{tmpfile.name}').to_crs('EPSG:4326')
            gdf = gdf[gdf.geometry.intersects(counties_gdf.unary_union)].copy()

            with transaction.atomic():
                for _, row in gdf.iterrows():
                    region = Region.objects.create(
                        name=row['GEOID'],
                        slug=row['GEOID'],
                        type=Region.Type.TRACT,
                        external_id=row['GEOID'],
                        geometry=to_multipolygon(row.geometry),
                        metadata={
                            'geoid': row['GEOID'],
                            'countyfp': row['COUNTYFP'],
                            'county_name': row['county_name'],
                            'namelsad': row.get('NAMELSAD', ''),
                            'statefp': row.get('STATEFP', '06'),
                        }
                    )
                    self.stdout.write(f'Imported: {region.name}')
