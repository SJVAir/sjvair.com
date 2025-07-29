import tempfile

import ckanapi
import geopandas as gpd
import pandas as pd
import requests

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from camp.apps.regions.models import Region
from camp.utils.gis import to_multipolygon

# CLASSFP: https://www.census.gov/library/reference/code-lists/class-codes.html


class Command(BaseCommand):
    help = 'Import California cities (places) into the Region table (limited to those within SJV counties)'

    def handle(self, *args, **options):
        Region.objects.filter(type__in=[Region.Type.CDP, Region.Type.CITY]).delete()

        ckan = ckanapi.RemoteCKAN('https://data.ca.gov')
        package = ckan.action.package_show(id='ca-geographic-boundaries')

        resource_name = 'CA Places Boundaries'
        resource = next(
            (r for r in package['resources'] if r['name'] == resource_name),
            None
        )
        if not resource:
            self.stderr.write(f'❌ Resource not found: {resource_name}')
            return

        with tempfile.NamedTemporaryFile(suffix='.zip') as tmpfile:
            self.stdout.write(f'Downloading city (place) shapefile from:\n{resource["url"]}\n')

            try:
                response = requests.get(resource['url'])
                response.raise_for_status()
            except requests.RequestException as e:
                self.stderr.write(f'❌ Failed to download place shapefile: {e}')
                return

            tmpfile.write(response.content)
            tmpfile.flush()

            # Read and reproject to WGS84
            counties_gdf = Region.objects.filter(type=Region.Type.COUNTY).to_dataframe()
            gdf = gpd.read_file(f'zip://{tmpfile.name}').to_crs('EPSG:4326')
            gdf = gdf[gdf.geometry.intersects(counties_gdf.unary_union)].copy()
            gdf = gdf.drop_duplicates(subset=['GEOID', 'NAMELSAD', 'CLASSFP', 'geometry'])

            with transaction.atomic():
                for _, row in gdf.iterrows():
                    if row['CLASSFP'] == 'C1':
                        region_type = Region.Type.CITY
                    elif row['CLASSFP'] in {'U1', 'U2'}:
                        region_type = Region.Type.CDP
                    else:
                        continue

                    region = Region.objects.create(
                        name=row['NAME'],
                        slug=slugify(row['NAME']),
                        type=region_type,
                        geometry=to_multipolygon(row.geometry),
                        metadata={
                            'geoid': row['GEOID'],
                            'name': row['NAME'],
                            'namelsad': row['NAMELSAD'],
                            'classfp': row['CLASSFP']
                        }
                    )
                    self.stdout.write(f'Imported: {region.name}')
