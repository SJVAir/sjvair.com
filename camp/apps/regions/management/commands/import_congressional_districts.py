from django.core.management.base import BaseCommand
from django.db import transaction

from camp.apps.regions.management.base import CountyFilterMixin
from camp.apps.regions.models import Region
from camp.utils import geodata
from camp.utils.gis import to_multipolygon

DATASET_URL = 'https://www2.census.gov/geo/tiger/TIGER2022/CD/tl_2022_06_cd118.zip'


class Command(CountyFilterMixin, BaseCommand):
    help = 'Import 116th Congressional Districts (2020) that intersect with San Joaquin Valley counties.'

    def add_arguments(self, parser):
        self.add_county_arguments(parser)

    def handle(self, *args, **options):
        print('\n--- Importing Congressional Districts ---')
        region_geometry = self.get_region_geometry(options.get('counties'))
        gdf = geodata.gdf_from_url(
            DATASET_URL, verify=False,
            limit_to_region=(region_geometry is None),
            region_geometry=region_geometry,
        )

        with transaction.atomic():
            for _, row in gdf.iterrows():
                region, created = Region.objects.import_or_update(
                    name=row.NAMELSAD20,
                    slug=f'cd-{row["CD118FP"]}',
                    type=Region.Type.CONGRESSIONAL_DISTRICT,
                    external_id=row.GEOID20,
                    version='2022',
                    geometry=to_multipolygon(row.geometry),
                    metadata={
                        'geoid': row.GEOID20,
                        'statefp': row.STATEFP20,
                        'district': row.CD118FP,
                        'namelsad': row.NAMELSAD20,
                        'session': row.CDSESSN,
                    },
                    boundary_metadata={
                        'aland': row.ALAND20,
                        'awater': row.AWATER20,
                    },
                )

                self.stdout.write(f'{region.get_type_display()} {"Imported" if created else "Updated"}: {region.name}')
