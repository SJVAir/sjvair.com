import pandas as pd

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from camp.apps.regions.models import Region
from camp.utils import geodata, gis

DATASET_URL = "https://www2.census.gov/geo/tiger/TIGER2010/TRACT/2010/tl_2010_06_tract10.zip"


class Command(BaseCommand):
    help = 'Import Census Tracts for the San Joaquin Valley'

    def handle(self, *args, **options):
        print('\n--- Importing Protected Areas ---')
        gdf = geodata.gdf_from_ckan(
            'california-protected-areas-database',
            resource_name='California Protected Areas Database 2025a release',
            limit_to_region=True
        )

        with transaction.atomic():
            for _, row in gdf.iterrows():
                region_name = row.LABEL_NAME or row.UNIT_NAME or row.SITE_NAME
                region, created = Region.objects.import_or_update(
                    name=region_name,
                    slug=slugify(region_name),
                    type=Region.Type.PROTECTED,
                    external_id=str(row.HOLDING_ID),
                    version='2025a',
                    geometry=gis.to_multipolygon(row.geometry),
                    metadata={
                        'access_type': row.ACCESS_TYP,
                        'unit_id': row.UNIT_ID,
                        'unit_name': row.UNIT_NAME,
                        'agency_id': row.AGNCY_ID,
                        'agency_name': row.AGNCY_NAME,
                        'agency_level': row.AGNCY_LEV,
                        'agency_type': row.AGNCY_TYP,
                        'agency_website': row.AGNCY_WEB,
                        'managing_agency_id': row.MNG_AG_ID,
                        'managing_agency': row.MNG_AGNCY,
                        'managing_agency_level': row.MNG_AG_LEV,
                        'managing_agency_type': row.MNG_AG_TYP,
                        'site_name': row.SITE_NAME,
                        'alt_site_name': row.ALT_SITE_N,
                        'park_url': row.PARK_URL,
                        'land_or_water': row.LAND_WATER,
                        'special_use': row.SPEC_USE,
                        'city': row.CITY,
                        'county': row.COUNTY,
                        'acres': row.ACRES,
                        'label_name': row.LABEL_NAME,
                        'date_revised': row.DATE_REVIS,
                        'year_protected': row.YR_PROTECT,
                        'year_established': row.YR_EST,
                        'gap_status': {
                            'gap1_acres': row.GAP1_acres,
                            'gap2_acres': row.GAP2_acres,
                            'gap3_acres': row.GAP3_acres,
                            'gap4_acres': row.GAP4_acres,
                            'total_gap_acres': row.GAP_tot_ac,
                            'gap_source': row.GAP_Source,
                        },
                    }
                )

                self.stdout.write(f'{region.get_type_display()} {"Imported" if created else "Updated"}: {region.name}')
