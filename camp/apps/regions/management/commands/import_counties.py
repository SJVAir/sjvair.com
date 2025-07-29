from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from camp.apps.regions.models import Region
from camp.utils import geodata
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
        gdf = geodata.gdf_from_ckan('ca-geographic-boundaries', resource_name='CA County Boundaries')
        gdf = gdf[gdf['NAME'].isin(SJV_COUNTIES)].copy()

        with transaction.atomic():
            for _, row in gdf.iterrows():
                region, created = Region.objects.update_or_create(
                    type=Region.Type.COUNTY,
                    external_id=row['GEOID'],
                    defaults={
                        'name': row['NAMELSAD'],
                        'slug': slugify(row['NAME']),
                        'geometry': to_multipolygon(row.geometry),
                        'metadata': {
                            'geoid': row['GEOID'],
                            'countyfp': row.get('COUNTYFP'),
                            'statefp': row.get('STATEFP'),
                            'name': row['NAME'],
                            'namelsad': row['NAMELSAD'],
                        }
                    }
                )
                self.stdout.write(f'{region.get_type_display()} {"Imported" if created else "Updated"}: {region.name}')
