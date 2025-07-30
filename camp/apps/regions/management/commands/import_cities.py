from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from camp.apps.regions.models import Region, Boundary
from camp.utils import geodata
from camp.utils.gis import to_multipolygon

# CLASSFP: https://www.census.gov/library/reference/code-lists/class-codes.html


class Command(BaseCommand):
    help = 'Import California cities (places) into the Region table (limited to those within SJV counties)'

    def handle(self, *args, **options):
        counties_gdf = Region.objects.filter(type=Region.Type.COUNTY).to_dataframe()
        gdf = geodata.gdf_from_ckan('ca-geographic-boundaries', resource_name='CA Places Boundaries')
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

                region, created = Region.objects.update_or_create(
                    external_id=row['GEOID'],
                    type=region_type,
                    defaults={
                        'name': row['NAME'],
                        'slug': slugify(row['NAME']),
                    }
                )

                boundary, created = Boundary.objects.update_or_create(
                    region_id=region.pk,
                    version='2023',
                    defaults={
                        'geometry': to_multipolygon(row.geometry),
                        'metadata': {
                            'geoid': row['GEOID'],
                            'name': row['NAME'],
                            'namelsad': row['NAMELSAD'],
                            'classfp': row['CLASSFP']
                        }
                    }
                )

                region.boundary = boundary
                region.save()

                self.stdout.write(f'{region.get_type_display()} {"Imported" if created else "Updated"}: {region.name}')
