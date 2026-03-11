import esri2gpd
import pandas as pd

from django.core.management.base import BaseCommand

from camp.apps.ces.models import CES4, DACCategory
from camp.apps.regions.models import Boundary, Region
from camp.apps.regions.utils import get_tract_relationships
from camp.utils import geodata
from camp.utils.geodata import load_region_geometry

# https://oehha.ca.gov/calenviroscreen/sb535
SB535_URL = 'https://services1.arcgis.com/PCHfdHz4GlDNAhBb/arcgis/rest/services/SB_535_Disadvantaged_Communities_2022/FeatureServer/0'

# Maps SB535 DAC_category strings to DACCategory integer choices
DAC_CATEGORY_MAP = {
    'CalEnviroScreen 4.0 Top 25%': DACCategory.TOP_CES_SCORE,
    'CalEnviroScreen 4.0 High Pollution Burden Score, Low Population Count': DACCategory.TOP_POLLUTION,
    'CalEnviroScreen 3.0 Disadvantaged Communities Only': DACCategory.PRIOR_DAC,
}

# Explicit mapping from CES4 shapefile columns to CES4 model fields.
# California-wide percentiles are preserved as published by OEHHA.
FIELD_MAP = {
    'TotPop19':   'population',
    'CIscore':    'ci_score',
    'CIscoreP':   'ci_score_p',
    # Pollution burden
    'PollBurd':   'pollution',
    'PolBurdSc':  'pollution_s',
    'PolBurdP':   'pollution_p',
    'Ozone':      'pol_ozone',
    'OzoneP':     'pol_ozone_p',
    'PM2_5':      'pol_pm',
    'PM2_5_P':    'pol_pm_p',
    'DieselPM':   'pol_diesel',
    'DieselPM_P': 'pol_diesel_p',
    'Pesticide':  'pol_pest',
    'PesticideP': 'pol_pest_p',
    'Tox_Rel':    'pol_rsei_haz',
    'Tox_Rel_P':  'pol_rsei_haz_p',
    'Traffic':    'pol_traffic',
    'TrafficP':   'pol_traffic_p',
    'DrinkWat':   'pol_drink',
    'DrinkWatP':  'pol_drink_p',
    'HazWaste':   'pol_haz',
    'HazWasteP':  'pol_haz_p',
    'Lead':       'pol_lead',
    'Lead_P':     'pol_lead_p',
    'Cleanup':    'pol_cleanups',
    'CleanupP':   'pol_cleanups_p',
    'GWThreat':   'pol_gwthreats',
    'GWThreatP':  'pol_gwthreats_p',
    'ImpWatBod':  'pol_iwb',
    'ImpWatBodP': 'pol_iwb_p',
    'SolWaste':   'pol_swis',
    'SolWasteP':  'pol_swis_p',
    # Population characteristics
    'PopChar':    'popchar',
    'PopCharSc':  'popchar_s',
    'PopCharP':   'popchar_p',
    'Asthma':     'char_asthma',
    'AsthmaP':    'char_asthma_p',
    'Cardiovas':  'char_cvd',
    'CardiovasP': 'char_cvd_p',
    'LowBirtWt':  'char_lbw',
    'LowBirWP':   'char_lbw_p',
    'Educatn':    'char_edu',
    'EducatP':    'char_edu_p',
    'Ling_Isol':  'char_ling',
    'Ling_IsolP': 'char_ling_p',
    'Poverty':    'char_pov',
    'PovertyP':   'char_pov_p',
    'Unempl':     'char_unemp',
    'UnemplP':    'char_unemp_p',
    'HousBurd':   'char_housingb',
    'HousBurdP':  'char_housingb_p',
    # Demographics
    'Child_10':   'pop_under_10',
    'Pop_10_64':  'pop_10_64',
    'Elderly65':  'pop_65_plus',
    'Hispanic':   'pop_hispanic',
    'White':      'pop_white',
    'AfricanAm':  'pop_black',
    'NativeAm':   'pop_native',
    'AAPI':       'pop_aapi',
    'OtherMult':  'pop_other',
}


class Command(BaseCommand):
    help = 'Import CalEnviroScreen 4.0 for both 2010 and 2020 census tract vintages.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--refresh',
            action='store_true',
            help='Re-download the Census tract relationship file.',
        )
        parser.add_argument(
            '--print-columns',
            action='store_true',
            help='Print shapefile columns and their FIELD_MAP mapping, then exit.',
        )

    def handle(self, *args, **options):
        ces4 = self.get_ces4()

        if options['print_columns']:
            self.print_columns(ces4)
            return

        tracts_2010 = self.get_tract_boundaries('2010')
        tracts_2020 = self.get_tract_boundaries('2020')

        rel = self.get_relationships(
            ces4_geoids=set(ces4['Tract']),
            geoids_2010=set(tracts_2010['GEOID']),
            geoids_2020=set(tracts_2020['GEOID']),
            refresh=options['refresh'],
        )

        ces4_2020 = self.remap_to_2020(ces4, tracts_2020, rel)

        self.stdout.write('\nSaving records...')
        self.save_records(ces4, geoid_col='Tract', version='2010')
        self.save_records(ces4_2020, geoid_col='Tract', version='2020')
        self.stdout.write(self.style.SUCCESS('\n✓ Done'))

    def get_ces4(self):
        """Download and filter CES4 shapefile, joining SB535 DAC status."""
        counties_union = load_region_geometry()

        gdf = geodata.gdf_from_ckan(
            dataset_id='calenviroscreen-4-0',
            resource_name='CalEnviroScreen 4.0 Results Shapefile',
            string_fields=['Tract'],
            limit_to_region=True,
            threshold=0.25,
        )
        gdf['Tract'] = gdf['Tract'].astype(str).str.zfill(11)

        sb535 = esri2gpd.get(SB535_URL)
        sb535 = sb535[
            sb535.geometry.apply(
                lambda g: (not g.is_empty and g.area > 0
                           and g.intersects(counties_union)
                           and g.intersection(counties_union).area / g.area >= 0.50)
            )
        ]
        sb535['Tract'] = sb535['Tract'].astype(str).str.zfill(11)

        dac_lookup = sb535.set_index('Tract')['DAC_category']
        gdf['dac_sb535'] = gdf['Tract'].isin(dac_lookup.index)
        gdf['dac_category'] = (
            gdf['Tract']
            .map(dac_lookup)
            .map(DAC_CATEGORY_MAP)
            .where(gdf['Tract'].isin(dac_lookup.index), other=None)
        )

        self.stdout.write(f'Loaded {len(gdf):,} CES4 tracts')
        return gdf

    def get_tract_boundaries(self, version):
        """Load tract boundaries for a given census vintage from the DB."""
        gdf = (Boundary.objects
            .filter(region__type=Region.Type.TRACT, version=version)
            .select_related('region')
            .to_dataframe()
        )
        gdf['GEOID'] = gdf['region__external_id']
        self.stdout.write(f'Loaded {len(gdf):,} tract boundaries for {version}')
        return gdf

    def get_relationships(self, ces4_geoids, geoids_2010, geoids_2020, refresh=False):
        """Load and filter the Census 2010→2020 tract relationship file."""
        rel = get_tract_relationships(refresh=refresh)
        rel = rel[rel['GEOID_TRACT_10'].isin(geoids_2010) | rel['GEOID_TRACT_20'].isin(geoids_2020)]
        rel = rel[rel['GEOID_TRACT_10'].isin(ces4_geoids)]
        self.stdout.write(f'{len(rel):,} relationship rows after filtering')

        missing = ces4_geoids - set(rel['GEOID_TRACT_10'])
        if missing:
            self.stdout.write(self.style.WARNING(f'⚠ {len(missing)} CES4 tracts not in relationship file'))
        else:
            self.stdout.write('✓ All CES4 tracts present in relationship file')

        return rel

    def remap_to_2020(self, ces4, tracts_2020, rel):
        """Area-weighted crosswalk of 2010 CES4 scores onto 2020 tract boundaries."""
        ces4_2020 = geodata.remap_gdf_boundaries(
            source=ces4.copy(),
            target=tracts_2020.copy(),
            rel=rel,
            source_geoid_col='Tract',
            target_geoid_col='GEOID',
            rel_source_col='GEOID_TRACT_10',
            rel_target_col='GEOID_TRACT_20',
        )
        self.stdout.write(f'✓ Remapped to {len(ces4_2020):,} 2020 tracts')
        return ces4_2020

    def save_records(self, gdf, geoid_col, version):
        """Upsert CES4 records for a given census vintage."""
        boundary_map = {
            b.region.external_id: b
            for b in (Boundary.objects
                .filter(region__type=Region.Type.TRACT, version=version)
                .select_related('region')
            )
        }

        created_count = updated_count = skipped_count = 0

        for _, row in gdf.iterrows():
            geoid = str(row[geoid_col]).zfill(11)
            boundary = boundary_map.get(geoid)

            if boundary is None:
                skipped_count += 1
                continue

            fields = {
                model_field: row.get(shp_col)
                for shp_col, model_field in FIELD_MAP.items()
                if shp_col in row.index
            }
            fields['dac_sb535'] = row.get('dac_sb535')
            dac_cat = row.get('dac_category')
            fields['dac_category'] = None if pd.isna(dac_cat) else int(dac_cat)

            _, created = CES4.objects.update_or_create(
                boundary=boundary,
                defaults=fields,
            )
            if created:
                created_count += 1
            else:
                updated_count += 1

        self.stdout.write(
            f'  {version}: {created_count} created, '
            f'{updated_count} updated, {skipped_count} skipped'
        )

    def print_columns(self, gdf):
        """Print shapefile columns alongside their FIELD_MAP target for verification."""
        self.stdout.write('CES4 shapefile columns:')
        for col in sorted(gdf.columns):
            mapped = FIELD_MAP.get(col, '—')
            self.stdout.write(f'  {col:30s} → {mapped}')

        unmapped = [
            c for c in gdf.columns
            if c not in FIELD_MAP and c not in ('Tract', 'geometry', 'dac_sb535', 'dac_category')
        ]
        if unmapped:
            self.stdout.write(self.style.WARNING(f'\n⚠ {len(unmapped)} unmapped columns: {unmapped}'))
