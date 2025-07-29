from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from camp.apps.regions.models import Region
from camp.utils import geodata
from camp.utils.gis import to_multipolygon


class Command(BaseCommand):
    help = 'Import California cities (places) into the Region table (limited to those within SJV counties)'

    def handle(self, *args, **options):
        Region.objects.filter(type__in=[Region.Type.SCHOOL_DISTRICT]).delete()

        counties_gdf = Region.objects.filter(type=Region.Type.COUNTY).to_dataframe()
        gdf = geodata.gdf_from_ckan('california-school-district-areas-2023-24')
        gdf = gdf[gdf.geometry.intersects(counties_gdf.unary_union)].copy()

        with transaction.atomic():
            for _, row in gdf.iterrows():
                region = Region.objects.create(
                    name=row['DistrictNa'],
                    slug=slugify(row['DistrictNa']),
                    type=Region.Type.SCHOOL_DISTRICT,
                    external_id=row['CDSCode'],
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
