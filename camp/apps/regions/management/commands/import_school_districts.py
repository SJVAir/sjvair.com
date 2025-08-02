from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils.text import slugify

from camp.apps.regions.models import Region
from camp.utils import geodata
from camp.utils.gis import to_multipolygon


class Command(BaseCommand):
    help = 'Import California cities (places) into the Region table (limited to those within SJV counties)'

    def handle(self, *args, **options):
        counties_gdf = Region.objects.filter(type=Region.Type.COUNTY).to_dataframe()
        gdf = geodata.gdf_from_ckan('california-school-district-areas-2023-24')
        gdf = gdf[gdf.geometry.intersects(counties_gdf.unary_union)].copy()

        with transaction.atomic():
            for _, row in gdf.iterrows():
                region, created = Region.objects.import_or_update(
                    name=row['DistrictNa'],
                    slug=slugify(row['DistrictNa']),
                    type=Region.Type.SCHOOL_DISTRICT,
                    external_id=row['CDSCode'],
                    version='2023-2024',
                    geometry=to_multipolygon(row.geometry),
                    metadata = {
                        # Identifiers
                        'fed_id': row['FedID'],
                        'cd_code': row['CDCode'],
                        'cds_code': row['CDSCode'],

                        # Geography & Classification
                        'district_name': row['DistrictNa'],
                        'county_name': row['CountyName'],
                        'district_type': row['DistrictTy'],
                        'grade_low': row['GradeLow'],
                        'grade_high': row['GradeHigh'],
                        'locale': row['LocaleDist'],  # NCES locale code

                        # Enrollment
                        'enrollment': {
                            'total': row['EnrollTota'],
                            'charter': row['EnrollChar'],
                            'non_charter': row['EnrollNonC'],
                        },

                        # Representation
                        'representation': {
                            'congress_us': row['CongressUS'],
                            'senate_ca': row['SenateCA'],
                            'assembly_ca': row['AssemblyCA'],
                        },

                        # Assistance
                        'assistance_status': row['AssistStat'],

                        # Demographics: Race / Ethnicity
                        'demographics': {
                            'african_american': {'count': row['AAcount'], 'pct': row['AApct']},
                            'american_indian': {'count': row['AIcount'], 'pct': row['AIpct']},
                            'asian': {'count': row['AScount'], 'pct': row['ASpct']},
                            'filipino': {'count': row['FIcount'], 'pct': row['FIpct']},
                            'hispanic_latino': {'count': row['HIcount'], 'pct': row['HIpct']},
                            'pacific_islander': {'count': row['PIcount'], 'pct': row['PIpct']},
                            'white': {'count': row['WHcount'], 'pct': row['WHpct']},
                            'multiracial': {'count': row['MRcount'], 'pct': row['MRpct']},
                            'not_reported': {'count': row['NRcount'], 'pct': row['NRpct']},
                        },

                        # Student Subgroups
                        'subgroups': {
                            'english_learners': {'count': row['ELcount'], 'pct': row['ELpct']},
                            'foster_youth': {'count': row['FOScount'], 'pct': row['FOSpct']},
                            'homeless': {'count': row['HOMcount'], 'pct': row['HOMpct']},
                            'migrant': {'count': row['MIGcount'], 'pct': row['MIGpct']},
                            'students_with_disabilities': {'count': row['SWDcount'], 'pct': row['SWDpct']},
                            'socioeconomically_disadvantaged': {'count': row['SEDcount'], 'pct': row['SEDpct']},
                        },
                    }
                )

                self.stdout.write(f'{region.get_type_display()} {"Imported" if created else "Updated"}: {region.name}')
