from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from camp.apps.regions.management.base import CountyFilterMixin
from camp.apps.regions.models import Region
from camp.utils import geodata, gis


def fix_encoding(value: str) -> str:
    try:
        return (value
            .encode('windows-1252')
             .decode('utf-8')
             .encode('windows-1252')
             .decode('utf-8')
        )
    except Exception:
        return value


class Command(CountyFilterMixin, BaseCommand):
    help = 'Import Land Use into the Region table'

    def add_arguments(self, parser):
        self.add_county_arguments(parser)

    def handle(self, *args, **options):
        print('\n--- Importing Land Use ---')
        region_geometry = self.get_region_geometry(options.get('counties'))
        series = geodata.iter_from_ckan(
            dataset_id='california-general-plan-land-use',
            limit_to_region=(region_geometry is None),
            region_geometry=region_geometry,
        )

        with transaction.atomic():
            for row in series:
                # Fix odd double-encoding issue.
                description = fix_encoding(row['descriptio'])
                region_name = row.jurisdicti
                if desc := (description.split(":")[0] if description else None):
                    region_name = f'{region_name} - {desc}'
                external_id = f'{row.County}-{row.jurisdicti}-{row.OBJECTID}'
                region, created = Region.objects.import_or_update(
                    name=region_name,
                    slug=slugify(region_name),
                    type=Region.Type.LAND_USE,
                    external_id=external_id,
                    version='2020',
                    geometry=gis.to_multipolygon(row.geometry),
                    metadata={
                        'county': row.County,
                        'jurisdiction': row.jurisdicti,
                        'land_use_class': row.classkey,
                        'land_use_code': row.code,
                        'land_use_description': description,
                        'ucd_number': row.ucd_number,
                        'ucd_description': row.ucd_descri,
                        'source': row.Source,
                        'source_date': row.Date,
                    }
                )

                self.stdout.write(f'{region.get_type_display()} {"Imported" if created else "Updated"}: {region.name}')
