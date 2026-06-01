from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from camp.apps.regions.managers import SJV_COUNTIES
from camp.apps.regions.models import Region
from camp.utils import geodata
from camp.utils.gis import to_multipolygon


class Command(BaseCommand):
    help = 'Import California counties into the Region table'

    def add_arguments(self, parser):
        parser.add_argument(
            '--county',
            action='append',
            dest='counties',
            metavar='NAME',
            help='County name(s) to import (can be used multiple times). '
                 'Defaults to SJV counties.',
        )

    def handle(self, *args, **options):
        # --county uses the short NAME form (e.g. "Los Angeles"); SJV_COUNTIES
        # uses NAMELSAD (e.g. "Fresno County") — keep them separate.
        short_names = set(options.get('counties') or [
            name.replace(' County', '') for name in SJV_COUNTIES
        ])

        print('\n--- Importing Counties ---')
        gdf = geodata.gdf_from_ckan('ca-geographic-boundaries', resource_name='CA County Boundaries')
        gdf = gdf[gdf['NAME'].isin(short_names)].copy()

        if gdf.empty:
            self.stderr.write(f'No counties found matching: {short_names}')
            return

        with transaction.atomic():
            for _, row in gdf.iterrows():
                region, created = Region.objects.import_or_update(
                    name=row.NAMELSAD,
                    slug=slugify(row.NAME),
                    type=Region.Type.COUNTY,
                    external_id=row.GEOID,
                    version='2023',
                    geometry=to_multipolygon(row.geometry),
                    metadata={
                        'geoid': row.GEOID,
                        'statefp': row.STATEFP,
                        'countyfp': row.COUNTYFP,
                        'name': row.NAME,
                        'namelsad': row.NAMELSAD,
                        'aland': row.ALAND,
                        'awater': row.AWATER,
                    }
                )

                self.stdout.write(f'{region.get_type_display()} {"Imported" if created else "Updated"}: {region.name}')
