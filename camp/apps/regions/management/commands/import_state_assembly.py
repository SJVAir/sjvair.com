from django.core.management.base import BaseCommand
from django.db import transaction

from camp.apps.regions.management.base import CountyFilterMixin
from camp.apps.regions.models import Region
from camp.utils import geodata
from camp.utils.gis import to_multipolygon


class Command(CountyFilterMixin, BaseCommand):
    help = 'Import State Assembly Districts into the Region table'

    def add_arguments(self, parser):
        self.add_county_arguments(parser)

    def handle(self, *args, **options):
        print('\n--- Importing State Assembly Districts ---')
        region_geometry = self.get_region_geometry(options.get('counties'))
        gdf = geodata.gdf_from_ckan(
            'assembly-districts',
            limit_to_region=(region_geometry is None),
            region_geometry=region_geometry,
        )

        with transaction.atomic():
            for _, row in gdf.iterrows():
                external_id = f"ad-{row.GEOID}"
                region, created = Region.objects.import_or_update(
                    name=row.AssemblyDi,
                    slug=external_id,
                    type=Region.Type.STATE_ASSEMBLY,
                    external_id=external_id,
                    version='2021',
                    geometry=to_multipolygon(row.geometry),
                )

                self.stdout.write(f'{region.get_type_display()} {"Imported" if created else "Updated"}: {region.name}')
