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
                region, created = Region.objects.import_or_update(
                    name=row['NAMELSAD'],
                    slug=slugify(row['NAME']),
                    type=Region.Type.COUNTY,
                    external_id=row['GEOID'],
                    version='2023',
                    geometry=to_multipolygon(row.geometry),
                    metadata={
                        'geoid': row['GEOID'],
                        'statefp': row['STATEFP'],
                        'countyfp': row['COUNTYFP'],
                        'name': row['NAME'],
                        'namelsad': row['NAMELSAD'],
                        'aland': row['ALAND'],
                        'awater': row['AWATER'],
                    }
                )

                self.stdout.write(f'{region.get_type_display()} {"Imported" if created else "Updated"}: {region.name}')
