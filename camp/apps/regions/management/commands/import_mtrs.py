from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from camp.apps.regions.models import Region
from camp.utils import geodata
from camp.utils.gis import to_multipolygon


def build_mtrs(meridian, township, range_, section):
    """Build a standardized MTRS external_id from PLSS component fields.

    e.g. ('MD', 'T13S', 'R14E', 8) -> 'MD-T13S-R14E-08'
    """
    return f'{meridian}-{township}-{range_}-{section:02d}'


class Command(BaseCommand):
    help = 'Import PLSS Sections (MTRS) from the California PLSS dataset on data.ca.gov.'

    def handle(self, *args, **options):
        self.stdout.write('Fetching PLSS Sections from data.ca.gov...')

        gdf = geodata.gdf_from_ckan(
            'public-land-survey-system-plss-sections',
            resource_name='GeoJSON',
            limit_to_region=True,
            threshold=0.0,
        )

        self.stdout.write(f'Loaded {len(gdf):,} sections. Importing...')

        created_count = updated_count = 0

        with transaction.atomic():
            for i, (_, row) in enumerate(gdf.iterrows(), 1):
                mtrs = build_mtrs(row.Meridian, row.Township, row.Range, int(row.Section))

                region, created = Region.objects.import_or_update(
                    name=mtrs,
                    slug=slugify(mtrs),
                    type=Region.Type.MTRS,
                    external_id=mtrs,
                    version='plss',
                    geometry=to_multipolygon(row.geometry),
                    metadata={
                        'meridian': row.Meridian,
                        'township': row.Township,
                        'range': row.Range,
                        'section': int(row.Section),
                        'mtrs': row.MTRS,
                    },
                )

                if created:
                    created_count += 1
                else:
                    updated_count += 1

                self.stdout.write(
                    f'  ({i:,}) {"Imported" if created else "Updated"}: {mtrs}',
                    ending='\r',
                )

        self.stdout.write(
            f'\nDone: {created_count:,} created, {updated_count:,} updated.'
        )
