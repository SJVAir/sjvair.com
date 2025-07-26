import tempfile
import requests
import geopandas as gpd

from django.core.management.base import BaseCommand
from django.contrib.gis.geos import GEOSGeometry, MultiPolygon

from camp.apps.regions.models import Region

TRACTS_URL = "https://www2.census.gov/geo/tiger/TIGER2020/TRACT/tl_2020_06_tract.zip"

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

def normalize_geom(geom):
    if geom.geom_type == 'Polygon':
        return MultiPolygon(geom)
    elif geom.geom_type == 'MultiPolygon':
        return geom
    raise ValueError(f'Unsupported geometry type: {geom.geom_type}')

class Command(BaseCommand):
    help = 'Import 2020 Census Tracts for San Joaquin Valley into the Region table'

    def handle(self, *args, **options):
        with tempfile.NamedTemporaryFile(suffix='.zip') as tmpfile:
            self.stdout.write('Downloading 2020 Census Tracts ZIP...')
            r = requests.get(TRACTS_URL)
            r.raise_for_status()
            tmpfile.write(r.content)
            tmpfile.flush()

            zip_path = f'zip://{tmpfile.name}'
            gdf = gpd.read_file(zip_path).to_crs('EPSG:4326')
            gdf = gdf[gdf['COUNTYFP'].isin(SJV_COUNTIES.keys())].copy()
            gdf['county_name'] = gdf['COUNTYFP'].map(SJV_COUNTIES)

            for _, row in gdf.iterrows():
                tract_code = row['GEOID']
                name = f'Tract {tract_code[-6:]}'
                slug = tract_code

                region = Region.objects.create(
                    name=name,
                    slug=slug,
                    type=Region.Type.TRACT,
                    geom=GEOSGeometry(normalize_geom(row.geometry).wkt, srid=4326),
                    metadata={
                        'geoid': tract_code,
                        'countyfp': row['COUNTYFP'],
                        'county_name': row['county_name'],
                        'namelsad': row.get('NAMELSAD', ''),
                        'statefp': row.get('STATEFP', '06'),
                    }
                )
                self.stdout.write(f'Imported: {region.name} ({region.slug})')
