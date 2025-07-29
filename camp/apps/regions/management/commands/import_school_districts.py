import tempfile

import ckanapi
import geopandas as gpd
import pandas as pd
import requests

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from camp.apps.regions.models import Region
from camp.utils.gis import to_multipolygon


class Command(BaseCommand):
    help = 'Import California cities (places) into the Region table (limited to those within SJV counties)'

    def handle(self, *args, **options):
        Region.objects.filter(type__in=[Region.Type.SCHOOL_DISTRICT]).delete()

        ckan = ckanapi.RemoteCKAN('https://data.ca.gov')
        package = ckan.action.package_show(id='california-school-district-areas-2023-24')

        resource_name = 'Shapefile'
        resource = next(
            (r for r in package['resources'] if r['name'] == resource_name),
            None
        )
        if not resource:
            self.stderr.write(f'❌ Resource not found: {resource_name}')
            return

        with tempfile.NamedTemporaryFile(suffix='.zip') as tmpfile:
            self.stdout.write(f'Downloading school district shapefile from:\n{resource["url"]}\n')

            try:
                response = requests.get(resource['url'])
                response.raise_for_status()
            except requests.RequestException as e:
                self.stderr.write(f'❌ Failed to download place shapefile: {e}')
                return

            tmpfile.write(response.content)
            tmpfile.flush()

            # Read and reproject to WGS84
            counties_gdf = Region.objects.filter(type=Region.Type.COUNTY).to_dataframe()
            gdf = gpd.read_file(f'zip://{tmpfile.name}').to_crs('EPSG:4326')
            gdf = gdf[gdf.geometry.intersects(counties_gdf.unary_union)].copy()

            with transaction.atomic():
                for _, row in gdf.iterrows():
                    region = Region.objects.create(
                        name=row['DistrictNa'],
                        slug=slugify(row['DistrictNa']),
                        type=Region.Type.SCHOOL_DISTRICT,
                        geometry=to_multipolygon(row.geometry),
                        metadata={
                            # Identifiers
                            'fed_id': row['FedID'],  # Federal District ID
                            'cd_code': row['CDCode'],  # County-District code
                            'cds_code': row['CDSCode'],  # 14-digit CDS code

                            # Geography & classification
                            'county_name': row['CountyName'],  # Name of the county
                            'district_type': row['DistrictTy'],  # Unified, Elementary, High, etc.
                            'grade_low': row['GradeLow'],  # Lowest grade served (e.g. KG)
                            'grade_high': row['GradeHigh'],  # Highest grade served (e.g. 12)

                            # Support status
                            'assistance_status': row['AssistStat'],  # Differentiated Assistance status

                            # Political representation
                            'congress_us': row['CongressUS'],  # US Congressional District(s)
                            'senate_ca': row['SenateCA'],  # California State Senate District(s)
                            'assembly_ca': row['AssemblyCA'],  # California State Assembly District(s)

                            # Locale classification
                            'locale': row['LocaleDist'],  # NCES locale code (e.g. "11 - City, Large")

                            # Enrollment totals
                            'enrollment_total': row['EnrollTota'],  # Total enrollment
                            'enrollment_charter': row['EnrollChar'],  # Charter enrollment
                            'enrollment_noncharter': row['EnrollNonC'],  # Non-charter enrollment

                            # Selected demographics (%)
                            'pct_hispanic': row['HIpct'],  # Percent Hispanic/Latino
                            'pct_white': row['WHpct'],  # Percent White
                            'pct_asian': row['ASpct'],  # Percent Asian
                            'pct_black': row['AApct'],  # Percent African American
                            'pct_multiracial': row['MRpct'],  # Percent Multi-Race
                            'pct_el': row['ELpct'],  # Percent English Learners
                            'pct_swd': row['SWDpct'],  # Percent Students with Disabilities
                            'pct_sed': row['SEDpct'],  # Percent Socioeconomically Disadvantaged
                        }
                    )
                    self.stdout.write(f'Imported: {region.name}')
