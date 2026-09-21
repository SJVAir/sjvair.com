from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from camp.apps.regions.management.base import CountyFilterMixin
from camp.apps.regions.models import Region
from camp.utils import geodata
from camp.utils.gis import to_multipolygon

# CLASSFP: https://www.census.gov/library/reference/code-lists/class-codes.html

# Local renames the Census place layer has not caught up with yet, keyed by
# GEOID. The source name is still recorded in the region's metadata
# (`name` / `namelsad`), so nothing is lost when Census updates and an
# entry here becomes a no-op.
NAME_OVERRIDES = {
    # Renamed from Squaw Valley by the Board on Geographic Names (2022) and
    # Fresno County; the Census CDP is still "Squaw Valley" as of TIGER 2023.
    '0673794': 'Yokuts Valley',
}


def place_name(geoid, source_name):
    return NAME_OVERRIDES.get(str(geoid), source_name)


class Command(CountyFilterMixin, BaseCommand):
    help = 'Import California cities (places) into the Region table'

    def add_arguments(self, parser):
        self.add_county_arguments(parser)

    def handle(self, *args, **options):
        print('\n--- Importing Cities / CDPs ---')
        region_geometry = self.get_region_geometry(options.get('counties'))
        gdf = geodata.gdf_from_ckan(
            'ca-geographic-boundaries',
            resource_name='CA Places Boundaries',
            limit_to_region=(region_geometry is None),
            region_geometry=region_geometry,
        )

        with transaction.atomic():
            for _, row in gdf.iterrows():
                if row.CLASSFP == 'C1':
                    region_type = Region.Type.CITY
                elif row.CLASSFP in {'U1', 'U2'}:
                    region_type = Region.Type.CDP
                else:
                    continue

                name = place_name(row.GEOID, row.NAME)
                region, created = Region.objects.import_or_update(
                    name=name,
                    slug=slugify(name),
                    type=region_type,
                    external_id=row.GEOID,
                    version='2023',
                    geometry=to_multipolygon(row.geometry),
                    metadata={
                        'geoid': row.GEOID,
                        'statefp': row.STATEFP,
                        'placefp': row.PLACEFP,
                        'name': row.NAME,
                        'namelsad': row.NAMELSAD,
                    },
                    boundary_metadata={
                        'aland': row.ALAND,
                        'awater': row.AWATER,
                    },
                )

                self.stdout.write(f'{region.get_type_display()} {"Imported" if created else "Updated"}: {region.name}')
