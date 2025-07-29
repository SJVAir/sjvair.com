import tempfile

import ckanapi
import requests
import geopandas as gpd

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from camp.apps.regions.models import Region
from camp.utils.gis import to_multipolygon

SJV_COUNTIES = {
    'Fresno',
    'Kern',
    'Kings',
    'Madera',
    'Merced',
    'San Joaquin',
    'Stanislaus',
    'Tulare',
}

class Command(BaseCommand):
    help = 'Import California counties into the Region table (limited to SJV)'

    def handle(self, *args, **options):
        ckan = ckanapi.RemoteCKAN('https://data.ca.gov')
        package = ckan.action.package_show(id='ca-geographic-boundaries')

        resource_name = 'CA County Boundaries'
        resource = next(
            (r for r in package['resources'] if r['name'] == resource_name),
            None
        )
        if not resource:
            self.stderr.write(f'❌ Resource not found: {resource_name}')
            return

        with tempfile.NamedTemporaryFile(suffix='.zip') as tmpfile:
            self.stdout.write(f'Downloading county shapefile from:\n{resource["url"]}\n')

            try:
                response = requests.get(resource['url'])
                response.raise_for_status()
            except requests.RequestException as e:
                self.stderr.write(f'❌ Failed to download county shapefile: {e}')
                return

            tmpfile.write(response.content)
            tmpfile.flush()

            gdf = gpd.read_file(f'zip://{tmpfile.name}').to_crs('EPSG:4326')
            gdf = gdf[gdf['NAME'].isin(SJV_COUNTIES)].copy()

            with transaction.atomic():
                for _, row in gdf.iterrows():
                    region = Region.objects.create(
                        name=row['NAMELSAD'],
                        slug=slugify(row['NAME']),
                        type=Region.Type.COUNTY,
                        external_id=row['GEOID'],
                        geometry=to_multipolygon(row.geometry),
                        metadata={
                            'geoid': row['GEOID'],
                            'countyfp': row.get('COUNTYFP'),
                            'statefp': row.get('STATEFP'),
                            'name': row['NAME'],
                            'namelsad': row['NAMELSAD'],
                        }
                    )
                    self.stdout.write(f'Imported: {region.name}')
