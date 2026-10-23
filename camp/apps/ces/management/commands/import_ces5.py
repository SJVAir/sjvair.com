import ckanapi
import pandas as pd

from django.core.management.base import BaseCommand

from camp.apps.ces import stats as ces_stats
from camp.apps.ces.models import CES5, DACCategory
from camp.apps.regions.models import Boundary, Region
from camp.utils import geodata

# https://data.ca.gov/dataset/calenviroscreen-5-0
CES5_DATASET_ID = 'calenviroscreen-5-0'
CES5_RESOURCE_NAME = 'CalEnviroScreen 5.0 Shapefile'

# CalEPA's final 2026 SB 535 DAC designation (September 2026), based on
# CalEnviroScreen 5.0: one row per designated tract, from the data.ca.gov CSV.
# https://calepa.ca.gov/programs/dac2026/
DAC_2026_DATASET_ID = 'sb-535-disadvantaged-communities-2026'
DAC_2026_RESOURCE_NAME = 'SB 535 Disadvantaged Communities - csv'

# Maps the designation's dac_type strings to DACCategory integer choices
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

        dac_lookup = self.apply_dac_designation(ces5)

        self.stdout.write('\nSaving records...')
        self.save_records(ces5)
        if dac_lookup is not None:
            self.reconcile_dac(dac_lookup)
        ces_stats.clear_caches()
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
        Join the final 2026 SB 535 DAC designation onto `gdf` by tract GEOID,
        mutating it in place with `dac_sb535`/`dac_category` columns. The CSV
        lists only designated tracts, so every other tract is False.

        If it can't be fetched or its schema doesn't match what we expect,
        warn and leave dac_sb535/dac_category null rather than failing the
        whole import -- the indicator data is still valid. Returns the
        designation ({tract: dac_type}), or None when it couldn't be read.
        """
        try:
            dac = self.get_dac_designation()
            dac_lookup = dac.set_index('tract')['dac_type']
            unknown = set(dac_lookup) - set(DAC_CATEGORY_MAP)
            if unknown:
                raise ValueError(f'unknown dac_type values: {sorted(unknown)}')
        except Exception as exc:
            self.stdout.write(self.style.WARNING(
                f'⚠ Could not fetch or interpret the 2026 DAC designation ({exc}); '
                'dac_sb535/dac_category will be left null for all tracts.'
            ))
            gdf['dac_sb535'] = None
            gdf['dac_category'] = None
            return None

        gdf['dac_sb535'] = gdf['tract'].isin(dac_lookup.index)
        gdf['dac_category'] = (
            gdf['tract']
            .map(dac_lookup)
            .map(DAC_CATEGORY_MAP)
            .where(gdf['tract'].isin(dac_lookup.index), other=None)
        )
        self.stdout.write(f'✓ {int(gdf["dac_sb535"].sum()):,} of {len(gdf):,} CES5 tracts are SB 535 DACs (2026, final)')
        return dac_lookup

    def reconcile_dac(self, dac_lookup):
        """
        Bring every stored CES5 record's SB 535 flag in line with the
        designation, not just the ones this run's file covered: a tract
        left over from an earlier import (or no longer in the region filter)
        that's marked a DAC but isn't designated comes off the list.
        """
        changed = 0
        for record in CES5.objects.select_related('boundary__region'):
            dac_type = dac_lookup.get(record.boundary.region.external_id)
            dac_sb535 = dac_type is not None
            dac_category = DAC_CATEGORY_MAP[dac_type] if dac_sb535 else None
            if (record.dac_sb535, record.dac_category) != (dac_sb535, dac_category):
                record.dac_sb535, record.dac_category = dac_sb535, dac_category
                record.save(update_fields=['dac_sb535', 'dac_category'])
                changed += 1
        self.stdout.write(f'  SB 535: {changed} record{"" if changed == 1 else "s"} outside this file corrected')

    def get_dac_designation(self):
        """The designated tracts, statewide: `tract` (11-digit GEOID) and `dac_type`."""
        ckan = ckanapi.RemoteCKAN('https://data.ca.gov')
        package = ckan.action.package_show(id=DAC_2026_DATASET_ID)
        resource = next((r for r in package['resources'] if r['name'] == DAC_2026_RESOURCE_NAME), None)
        if resource is None:
            raise ValueError(f'resource not found: {DAC_2026_RESOURCE_NAME}')
        dac = pd.read_csv(resource['url'], dtype={'tract': str}, encoding='utf-8-sig')
        # The CSV writes the GEOID as a float ("6001400900.000..."), dropping the leading zero.
        dac['tract'] = dac['tract'].str.split('.').str[0].str.zfill(11)
        return dac[['tract', 'dac_type']]

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
