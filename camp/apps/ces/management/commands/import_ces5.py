import esri2gpd
import pandas as pd

from django.core.management.base import BaseCommand

from camp.apps.ces.models import CES5, DACCategory
from camp.apps.regions.models import Boundary, Region
from camp.utils import geodata
from camp.utils.geodata import load_region_geometry

# https://data.ca.gov/dataset/calenviroscreen-5-0
CES5_DATASET_ID = 'calenviroscreen-5-0'
CES5_RESOURCE_NAME = 'CalEnviroScreen 5.0 Shapefile'

# DRAFT 2026 SB535 DAC designation, based on CalEnviroScreen 5.0.
# CalEPA's public comment period runs through Aug 14, 2026 — this command
# is idempotent, so re-run it once the designation is finalized.
# https://calepa.ca.gov/programs/dac2026/
DRAFT_DAC_2026_URL = 'https://services1.arcgis.com/PCHfdHz4GlDNAhBb/arcgis/rest/services/DRAFT_SB535_Disadvantaged_Communities_2026/FeatureServer/0'

# Maps the draft layer's dac_type strings to DACCategory integer choices
DAC_CATEGORY_MAP = {
    'CES 5.0 Top 25%': DACCategory.TOP_CES_SCORE,
    'CES 5.0 High Pollution/Low Population': DACCategory.TOP_POLLUTION,
    'CES 4.0 Carry-Over DAC': DACCategory.PRIOR_DAC,
}

# Explicit mapping from CES5 shapefile columns to CES5 model fields.
# California-wide percentiles are preserved as published by OEHHA.
FIELD_MAP = {
    'zipcode':    'zipcode',
    'approx_loc': 'approx_loc',
    'county':     'county',
    'region':     'region_name',
    'ACS2024Pop': 'population',
    'CIscore':    'ci_score',
    'CIscoreP':   'ci_score_p',
    # Pollution burden
    'ozone':      'pol_ozone',
    'ozoneP':     'pol_ozone_p',
    'pm':         'pol_pm',
    'pmP':        'pol_pm_p',
    'diesel':     'pol_diesel',
    'dieselP':    'pol_diesel_p',
    'pest':       'pol_pest',
    'pestP':      'pol_pest_p',
    'RSEIhaz':    'pol_rsei_haz',
    'RSEIhazP':   'pol_rsei_haz_p',
    'traffic':    'pol_traffic',
    'trafficP':   'pol_traffic_p',
    'drink':      'pol_drink',
    'drinkP':     'pol_drink_p',
    'lead':       'pol_lead',
    'leadP':      'pol_lead_p',
    'cleanups':   'pol_cleanups',
    'cleanupsP':  'pol_cleanups_p',
    'gwthreats':  'pol_gwthreats',
    'gwthreatsP': 'pol_gwthreats_p',
    'haz':        'pol_haz',
    'hazP':       'pol_haz_p',
    'iwb':        'pol_iwb',
    'iwbP':       'pol_iwb_p',
    'SmATS':      'pol_small_ats',
    'SmATSP':     'pol_small_ats_p',
    'swis':       'pol_swis',
    'swisP':      'pol_swis_p',
    'Pollution':  'pollution',
    'PollutionS': 'pollution_s',
    'PollutionP': 'pollution_p',
    # Population characteristics
    'asthma':     'char_asthma',
    'asthmaP':    'char_asthma_p',
    'cvd':        'char_cvd',
    'cvdP':       'char_cvd_p',
    'diabetes':   'char_diabetes',
    'diabetesP':  'char_diabetes_p',
    'lbw':        'char_lbw',
    'lbwP':       'char_lbw_p',
    'edu':        'char_edu',
    'eduP':       'char_edu_p',
    'ling':       'char_ling',
    'lingP':      'char_ling_p',
    'pov':        'char_pov',
    'povP':       'char_pov_p',
    'unemp':      'char_unemp',
    'unempP':     'char_unemp_p',
    'housingB':   'char_housingb',
    'housingBP':  'char_housingb_p',
    'PopChar':    'popchar',
    'PopCharSco': 'popchar_s',
    'PopCharP':   'popchar_p',
    # Demographics (percentages)
    'pop_und10':  'pop_under_10_pct',
    'pop_10_64':  'pop_10_64_pct',
    'pop_ov64':   'pop_65_plus_pct',
    'hisp':       'pop_hispanic_pct',
    'white':      'pop_white_pct',
    'black':      'pop_black_pct',
    'amind':      'pop_native_pct',
    'asian':      'pop_asian_pct',
    'pacisl':     'pop_pacisl_pct',
    'othmult':    'pop_other_pct',
}


def _clean_value(v):
    """
    Convert NaN to None and snap float drift near -999 to exactly -999;
    non-numeric values (e.g. CES5's zipcode/approx_loc strings) pass through unchanged.
    """
    if pd.isna(v):
        return None
    if isinstance(v, (int, float)) and abs(v - (-999)) <= 1:
        return -999
    return v


class Command(BaseCommand):
    help = 'Import CalEnviroScreen 5.0 (2020 census tracts only — CES5 is natively 2020-vintage).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--print-columns',
            action='store_true',
            help='Print shapefile columns and their FIELD_MAP mapping, then exit.',
        )

    def handle(self, *args, **options):
        ces5 = self.get_ces5()

        if options['print_columns']:
            self.print_columns(ces5)
            return

        self.apply_dac_designation(ces5)

        self.stdout.write('\nSaving records...')
        self.save_records(ces5)
        self.stdout.write(self.style.SUCCESS('\n✓ Done'))

    def get_ces5(self):
        """Download and filter the CES5 shapefile to the SJV region."""
        gdf = geodata.gdf_from_ckan(
            dataset_id=CES5_DATASET_ID,
            resource_name=CES5_RESOURCE_NAME,
            string_fields=['tract'],
            limit_to_region=True,
            threshold=0.25,
        )
        gdf['tract'] = gdf['tract'].astype(str).str.zfill(11)
        self.stdout.write(f'Loaded {len(gdf):,} CES5 tracts')
        return gdf

    def apply_dac_designation(self, gdf):
        """
        Join the draft 2026 SB535 DAC designation onto `gdf` by tract GEOID,
        mutating it in place with `dac_sb535`/`dac_category` columns.

        This layer is a DRAFT (public comment through Aug 14, 2026). If it
        can't be fetched or its schema doesn't match what we expect, warn and
        leave dac_sb535/dac_category null rather than failing the whole
        import — the indicator data is still valid.
        """
        try:
            counties_union = load_region_geometry()
            dac = esri2gpd.get(DRAFT_DAC_2026_URL)
            dac = dac[
                dac.geometry.apply(
                    lambda g: (not g.is_empty and g.area > 0
                               and g.intersects(counties_union)
                               and g.intersection(counties_union).area / g.area >= 0.50)
                )
            ]
            dac['tract'] = dac['tract'].astype(str).str.zfill(11)
            dac_lookup = dac.set_index('tract')['dac_type']
        except Exception as exc:
            self.stdout.write(self.style.WARNING(
                f'⚠ Could not fetch or interpret draft DAC 2026 layer ({exc}); '
                'dac_sb535/dac_category will be left null for all tracts.'
            ))
            gdf['dac_sb535'] = None
            gdf['dac_category'] = None
            return

        gdf['dac_sb535'] = gdf['tract'].isin(dac_lookup.index)
        gdf['dac_category'] = (
            gdf['tract']
            .map(dac_lookup)
            .map(DAC_CATEGORY_MAP)
            .where(gdf['tract'].isin(dac_lookup.index), other=None)
        )

        missing = set(gdf['tract']) - set(dac_lookup.index)
        if missing:
            self.stdout.write(self.style.WARNING(
                f'⚠ {len(missing)} CES5 tracts not in the draft DAC 2026 layer '
                '(dac_sb535/dac_category left null for those tracts)'
            ))
        else:
            self.stdout.write('✓ All CES5 tracts present in the draft DAC 2026 layer')

    def save_records(self, gdf):
        """Upsert CES5 records for the 2020 vintage."""
        boundary_map = {
            b.region.external_id: b
            for b in (Boundary.objects
                .filter(region__type=Region.Type.TRACT, version='2020')
                .select_related('region')
            )
        }

        created_count = updated_count = skipped_count = 0

        for _, row in gdf.iterrows():
            geoid = str(row['tract']).zfill(11)
            boundary = boundary_map.get(geoid)

            if boundary is None:
                skipped_count += 1
                continue

            fields = {
                model_field: _clean_value(row.get(shp_col))
                for shp_col, model_field in FIELD_MAP.items()
                if shp_col in row.index
            }
            dac_sb535 = row.get('dac_sb535')
            fields['dac_sb535'] = None if pd.isna(dac_sb535) else bool(dac_sb535)
            dac_cat = row.get('dac_category')
            fields['dac_category'] = None if pd.isna(dac_cat) else int(dac_cat)

            _, created = CES5.objects.update_or_create(
                boundary=boundary,
                defaults=fields,
            )
            if created:
                created_count += 1
            else:
                updated_count += 1

        self.stdout.write(
            f'  2020: {created_count} created, '
            f'{updated_count} updated, {skipped_count} skipped'
        )

    def print_columns(self, gdf):
        """Print shapefile columns alongside their FIELD_MAP target for verification."""
        self.stdout.write('CES5 shapefile columns:')
        for col in sorted(gdf.columns):
            mapped = FIELD_MAP.get(col, '—')
            self.stdout.write(f'  {col:30s} → {mapped}')

        unmapped = [
            c for c in gdf.columns
            if c not in FIELD_MAP and c not in ('tract', 'geometry')
        ]
        if unmapped:
            self.stdout.write(self.style.WARNING(f'\n⚠ {len(unmapped)} unmapped columns: {unmapped}'))
