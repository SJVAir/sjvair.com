import tempfile
from pathlib import Path

import esri2gpd
import geopandas as gpd
import pandas as pd
import requests

from django.core.management.base import BaseCommand

from camp.apps.regions.models import Region, Boundary
from camp.utils import geodata


RELATIONSHIP_URL = 'https://www2.census.gov/geo/docs/maps-data/data/rel2020/tract/tab20_tract20_tract10_natl.txt'
CACHE_PATH = Path(f'{tempfile.tempdir}/tract_2010_2020_relationship.txt')

# https://oehha.ca.gov/calenviroscreen/sb535
SB535DAC_URL = 'https://services1.arcgis.com/PCHfdHz4GlDNAhBb/arcgis/rest/services/SB_535_Disadvantaged_Communities_2022/FeatureServer/0'


def get_relationships(refresh: bool = False) -> pd.DataFrame:
    if refresh or not CACHE_PATH.exists():
        print('Downloading relationship file...')
        response = requests.get(RELATIONSHIP_URL, verify=False)
        response.raise_for_status()
        CACHE_PATH.write_text(response.text)
    else:
        print(f'Using cached file at {CACHE_PATH}')

    df = pd.read_csv(CACHE_PATH, dtype=str, sep='|')
    print(f'Loaded {len(df):,} rows from relationship file')
    return df


def get_ces4() -> pd.DataFrame:
    counties_gdf = Region.objects.filter(type=Region.Type.COUNTY).to_dataframe()
    gdf = geodata.gdf_from_zip('https://gis.data.ca.gov/api/download/v1/items/b6e0a01c423b489f8d98af641445da28/shapefile?layers=0')
    gdf['Tract'] = gdf['tract']
    gdf = geodata.filter_by_overlap(gdf, counties_gdf.unary_union, 0.25)
    gdf['Tract'] = gdf['Tract'].astype(str).str.zfill(11)

    # Get the SB535 Disadvantaged Communities dataset and filter by county
    sb535dac = esri2gpd.get(SB535DAC_URL)
    sb535dac = geodata.filter_by_overlap(sb535dac, counties_gdf.unary_union, 0.50)
    sb535dac['Tract'] = sb535dac['Tract'].astype(str).str.zfill(11)

    # Get the DAC status for each CES4 record
    dac_lookup = sb535dac.set_index('Tract')['DAC_category']
    gdf['dac_sb535'] = gdf['Tract'].isin(dac_lookup.index)
    gdf['dac_category'] = gdf['Tract'].map(dac_lookup).where(pd.notnull, None)

    print(f'Loaded {len(gdf):,} CES4 tracts after filtering by SJV overlap')
    return gdf


def get_tract_boundaries(version: str) -> pd.DataFrame:
    gdf = Boundary.objects.filter(
        region__type=Region.Type.TRACT,
        version=version
    ).select_related('region').to_dataframe()
    gdf['GEOID'] = gdf['region__external_id']
    print(f'Loaded {len(gdf):,} tract boundaries for {version}')
    return gdf


def build_ces4_2020(ces4: pd.DataFrame, rel: pd.DataFrame, tracts_2020: pd.DataFrame) -> gpd.GeoDataFrame:
    # Ensure merge keys are str and padded
    rel['GEOID_TRACT_10'] = rel['GEOID_TRACT_10'].astype(str).str.zfill(11)
    rel['GEOID_TRACT_20'] = rel['GEOID_TRACT_20'].astype(str).str.zfill(11)

    # Add CES4 columns to relationship file
    merged = rel.merge(ces4, left_on='GEOID_TRACT_10', right_on='Tract', how='inner')

    # Convert area field to numeric and compute weight
    merged['AREALAND_PART'] = pd.to_numeric(merged['AREALAND_PART'], errors='coerce')
    merged['weight'] = merged['AREALAND_PART'] / merged.groupby('GEOID_TRACT_10')['AREALAND_PART'].transform('sum')

    # Warn about partial mappings
    check = merged.groupby('GEOID_TRACT_10')['weight'].sum().reset_index()
    bad = check[check['weight'] < 0.99]
    print(f'⚠️ {len(bad)} tracts have weights summing to less than 0.99')

    # Weighted numeric aggregation
    exclude_cols = ['Tract', 'ZIP', 'County', 'ApproxLoc', 'geometry', 'dac_category']
    numeric_cols = [col for col in ces4.columns if col not in exclude_cols and pd.api.types.is_numeric_dtype(ces4[col])]
    for col in numeric_cols:
        merged[col] = merged[col] * merged['weight']
    weighted = merged.groupby('GEOID_TRACT_20')[numeric_cols].sum().reset_index()

    # Find dominant tract for each 2020 tract and its DAC category
    merged['weight_rank'] = merged.groupby('GEOID_TRACT_20')['weight'].rank(ascending=False, method='first')
    dominant = merged.loc[merged['weight_rank'] == 1, ['GEOID_TRACT_20', 'dac_category']]

    # Add geometry and dac_category
    out = tracts_2020[['GEOID', 'geometry']].rename(columns={'GEOID': 'GEOID_TRACT_20'})
    out = out.merge(weighted, on='GEOID_TRACT_20', how='inner')
    out = out.merge(dominant, on='GEOID_TRACT_20', how='left')

    return gpd.GeoDataFrame(out, geometry='geometry', crs=tracts_2020.crs)



def show_split_example(ces4, ces4_2020, rel, col='CIscore'):
    rel = rel.copy()
    rel['GEOID_TRACT_10'] = rel['GEOID_TRACT_10'].astype(str).str.zfill(11)
    rel['GEOID_TRACT_20'] = rel['GEOID_TRACT_20'].astype(str).str.zfill(11)

    vc = rel['GEOID_TRACT_10'].value_counts()
    example = vc[vc > 1].index[0]

    print(f'🧪 Example: CES4 tract {example} was split across {vc[example]} 2020 tracts')
    rows = rel[rel['GEOID_TRACT_10'] == example].copy()
    rows = rows.merge(ces4[['Tract', col]], left_on='GEOID_TRACT_10', right_on='Tract', how='left')
    rows['AREALAND_PART'] = pd.to_numeric(rows['AREALAND_PART'], errors='coerce')
    rows['weight'] = rows['AREALAND_PART'] / rows['AREALAND_PART'].sum()
    rows['weighted_value'] = rows[col] * rows['weight']

    print(rows[['GEOID_TRACT_10', 'GEOID_TRACT_20', col, 'weight', 'weighted_value']])

    # Compare to result
    value_2020 = ces4_2020.loc[ces4_2020['GEOID_TRACT_20'].isin(rows['GEOID_TRACT_20']), col]
    print(f'\nWeighted average value applied to 2020 tracts:\n{value_2020}')


class Command(BaseCommand):
    help = 'Analyze how CES4 tracts (2010) map to 2020 census tracts using the relationship file'

    def add_arguments(self, parser):
        parser.add_argument('--refresh', action='store_true', help='Re-download tract relationship file')

    def handle(self, *args, **options):
        rel = get_relationships(refresh=options['refresh'])
        ces4 = get_ces4()
        tracts_2010 = get_tract_boundaries('2010')
        tracts_2020 = get_tract_boundaries('2020')

        geoids_2010 = set(tracts_2010['GEOID'])
        geoids_2020 = set(tracts_2020['GEOID'])
        ces4_geoids = set(ces4['Tract'])

        # Filter rel file to just tracts we have
        rel = rel[rel['GEOID_TRACT_10'].isin(geoids_2010) | rel['GEOID_TRACT_20'].isin(geoids_2020)]
        print(f'{len(rel):,} rows remaining in relationship file after filtering')

        # CES4 tracts missing from the relationship file
        missing = ces4_geoids - set(rel['GEOID_TRACT_10'])
        if missing:
            print(f'⚠️ {len(missing)} CES4 tracts missing from relationship file:')
            for geoid in sorted(missing):
                print(f'  - {geoid}')
        else:
            print('✅ All CES4 tracts are present in the relationship file')

        # Mapping analysis
        rel = rel[rel['GEOID_TRACT_10'].isin(ces4_geoids)]

        ces4_2020 = build_ces4_2020(ces4, rel, tracts_2020)
        print(f'✅ Built ces4_2020 GeoDataFrame with {len(ces4_2020):,} rows')

        mapping_counts = rel['GEOID_TRACT_10'].value_counts()
        one_to_one = mapping_counts[mapping_counts == 1].count()
        one_to_many = mapping_counts[mapping_counts > 1].count()

        reverse_counts = rel['GEOID_TRACT_20'].value_counts()
        many_to_one = reverse_counts[reverse_counts > 1].count()

        from camp.apps.integrate.ces4.models import Tract
        from camp.apps.integrate.ces4.data import Ces4Data
        params = {Ces4Data.normalize(f.name): f.name for f in Tract._meta.get_fields()}
        ces4 = get_ces4()
        ces4_2020 = build_ces4_2020(ces4, rel, tracts_2020)
        q = Ces4Data.to_db(ces4, params, 2010)
        r = Ces4Data.to_db(ces4_2020, params, 2020)
        

        print('\n--- Mapping Summary ---')
        print(f'CES4 tracts: {len(ces4)}')
        print(f'2020 tracts: {len(ces4_2020)}')
        print(f'1:1 mappings (CES4 to 2020): {one_to_one}')
        print(f'1:many mappings (CES4 split across multiple 2020 tracts): {one_to_many}')
        print(f'Many:1 mappings (multiple CES4 tracts map to one 2020 tract): {many_to_one}')

        print('\n--- Split Example ---')
        show_split_example(ces4, ces4_2020, rel)

        # import code
        # code.interact(local=locals())
