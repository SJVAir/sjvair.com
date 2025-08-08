from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from camp.apps.regions.models import Region
from camp.utils import geodata
from camp.utils.gis import to_multipolygon

DATASET_URL = "https://www2.census.gov/geo/tiger/TIGER2010/TRACT/2010/tl_2010_06_tract10.zip"


class Command(BaseCommand):
    help = 'Import Census Tracts for the San Joaquin Valley'

    def handle(self, *args, **options):
        print('\n--- Importing Land Use ---')
        gdf = geodata.gdf_from_ckan('california-general-plan-land-use', limit_to_counties=True)

        # Fix odd double-encoding issue.
        gdf['descriptio'] = gdf['descriptio'].apply(
            lambda s: (s
                .encode('windows-1252')
                .decode('utf-8')
                .encode('windows-1252')
                .decode('utf-8')
                if isinstance(s, str) else None
            ))

        with transaction.atomic():
            for _, row in gdf.iterrows():
                region_name = row.jurisdicti
                if desc := (row.descriptio.split(":")[0] if row.descriptio else None):
                    region_name = f'{region_name} - {desc}'
                external_id = f'{row.County}-{row.jurisdicti}-{row.OBJECTID}'
                region, created = Region.objects.import_or_update(
                    name=region_name,
                    slug=slugify(region_name),
                    type=Region.Type.LAND_USE,
                    external_id=external_id,
                    version='2020',
                    geometry=to_multipolygon(row.geometry),
                    metadata={
                        'county': row.County,
                        'jurisdiction': row.jurisdicti,
                        'land_use_class': row.classkey,
                        'land_use_code': row.code,
                        'land_use_description': row.descriptio,
                        'ucd_number': row.ucd_number,
                        'ucd_description': row.ucd_descri,
                        'source': row.Source,
                        'source_date': row.Date,
                    }
                )

                self.stdout.write(f'{region.get_type_display()} {"Imported" if created else "Updated"}: {region.name}')
