from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from camp.apps.regions.management.base import CountyFilterMixin
from camp.apps.regions.models import Region
from camp.utils import geodata
from camp.utils.gis import to_multipolygon


class Command(CountyFilterMixin, BaseCommand):
    help = 'Import Urban Areas into the Region table'

    def add_arguments(self, parser):
        self.add_county_arguments(parser)

    def handle(self, *args, **options):
        print('\n--- Importing Urban Areas ---')
        region_geometry = self.get_region_geometry(options.get('counties'))
        gdf = geodata.gdf_from_ckan(
            '2020-adjusted-urban-area',
            limit_to_region=(region_geometry is None),
            region_geometry=region_geometry,
        )

        with transaction.atomic():
            for _, row in gdf.iterrows():
                name = row.NAME
                if name.endswith(', CA'):
                    name = name[:-4]
                region, created = Region.objects.import_or_update(
                    name=name,
                    slug=slugify(name),
                    type=Region.Type.URBAN_AREA,
                    external_id=row.UACE20,
                    version='2020',
                    geometry=to_multipolygon(row.geometry),
                    metadata={
                        'uace10': row.UACE10,
                        'uace20': row.UACE20,
                        'population': row.Population,
                        'area_sqm': row.Area_sqm,
                        'urban_area_type': 'urbanized' if row.UrbanAreas == 2 else 'small_urban',
                        'urban_area_code': row.UrbanAreas
                    }
                )

                self.stdout.write(f'{region.get_type_display()} {"Imported" if created else "Updated"}: {region.name}')
