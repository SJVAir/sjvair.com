import math

from pathlib import Path

import esri2gpd
import requests
import pandas as pd

from django.core.management.base import BaseCommand
from django.db import transaction

from camp.apps.regions.models import Region
from camp.utils import geodata
from camp.utils.gis import to_multipolygon

TRACTS_2010_URL = "https://www2.census.gov/geo/tiger/TIGER2010/TRACT/2010/tl_2010_06_tract10.zip"
TRACTS_2020_URL = 'https://www2.census.gov/geo/tiger/TIGER2020/TRACT/tl_2020_06_tract.zip'

RUCA_2020_URL = 'https://ers.usda.gov/sites/default/files/_laserfiche/DataFiles/53241/RUCA-codes-2020-tract.csv?v=27807'
RUCA_2010_URL = 'https://ers.usda.gov/sites/default/files/_laserfiche/DataFiles/53241/ruca2010revised.xlsx?v=51200'
SB535DAC_URL = 'https://services1.arcgis.com/PCHfdHz4GlDNAhBb/arcgis/rest/services/SB_535_Disadvantaged_Communities_2022/FeatureServer/0'

RELATIONSHIP_URL = 'https://www2.census.gov/geo/docs/maps-data/data/rel2020/tract/tab20_tract20_tract10_natl.txt'
RELATIONSHIP_CACHE = Path(f'{geodata.GEODATA_CACHE_DIR}/tract_2010_2020_relationship.txt')


class Command(BaseCommand):
    help = 'Import Census Tracts for the San Joaquin Valley'

    def handle(self, *args, **options):
        print('\n--- Importing Census Tracts (2010) ---')

        # Census tracts and relationship file
        tracts_2020 = self.load_2020_tracts()
        tracts_2010 = self.load_2010_tracts()
        rel = self.load_tract_relationships()

        # 2020 Rural/Urban Commuting Areas
        ruca_2020 = self.load_ruca_2020()
        ruca_2020 = ruca_2020[ruca_2020['geoid'].isin(tracts_2020['geoid'])]
        ruca_2020['ruca_category'] = ruca_2020['ruca_code'].apply(self.ruca_category)
        ruca_2020['ruca_description'] = ruca_2020['ruca_code'].apply(self.ruca_description)

        # 2010 Rural/Urban Commuting Areas
        ruca_2010_xls = self.load_ruca_2010_xls()
        ruca_2010_xls = ruca_2010_xls[ruca_2010_xls['geoid'].isin(tracts_2020['geoid'])]
        ruca_2010 = geodata.remap_gdf_boundaries(
            source=ruca_2020.copy(),
            target=tracts_2010.copy(),
            rel=rel,
            rel_source_col='GEOID_TRACT_20',
            rel_target_col='GEOID_TRACT_10',
        ).drop(columns=['geometry'])

        ruca_2010 = self.resolve_ruca_2010(ruca_2010, ruca_2010_xls)
        ruca_2010['ruca_category'] = ruca_2010['ruca_code'].apply(self.ruca_category)
        ruca_2010['ruca_description'] = ruca_2010['ruca_code'].apply(self.ruca_description)

        # SB535 Disadvantaged Communities
        dac_2010 = self.load_sb535_dac()
        dac_2020 = geodata.remap_gdf_boundaries(
            source=dac_2010.copy(),
            target=tracts_2020.copy(),
            rel=rel,
            rel_source_col='GEOID_TRACT_10',
            rel_target_col='GEOID_TRACT_20',
        ).drop(columns=['geometry'])

        # Merge RUCA and SB535 into 2010 census tracts
        tracts_2020 = tracts_2020.merge(ruca_2020, on='geoid', how='left')
        tracts_2020 = tracts_2020.merge(dac_2020, on='geoid', how='left')
        tracts_2020['dac_status'] = tracts_2020['dac_category'].notna()
        tracts_2020['dac_category'] = tracts_2020['dac_category'].fillna('')

        # Merge RUCA and SB535 into 2020 census tracts
        tracts_2010 = tracts_2010.merge(ruca_2010, on='geoid', how='left')
        tracts_2010 = tracts_2010.merge(dac_2010, on='geoid', how='left')
        tracts_2010['dac_status'] = tracts_2010['dac_category'].notna()
        tracts_2010['dac_category'] = tracts_2010['dac_category'].fillna('')

        with transaction.atomic():
            for gdf in [tracts_2020, tracts_2010]:
                for _, row in gdf.iterrows():
                    region, created = Region.objects.import_or_update(
                        name=row.geoid,
                        slug=row.geoid,
                        type=Region.Type.TRACT,
                        external_id=row.geoid,
                        version=row.version,
                        geometry=to_multipolygon(row.geometry),
                        metadata={
                            'geoid': row.geoid,
                            'statefp': row.statefp,
                            'countyfp': row.countyfp,
                            'tractce': row.tractce,
                            'name': row.name,
                            'namelsad': row.namelsad,
                            'aland': row.aland,
                            'awater': row.awater,
                            'dac': self.extract_columns(row, 'dac_'),
                            'ruca': self.extract_columns(row, 'ruca_'),
                        }
                    )

                    self.stdout.write(f'{region.get_type_display()} {"Imported" if created else "Updated"}: {region.name}')


    def load_2020_tracts(self) -> pd.DataFrame:
        print('\nLoading 2020 tracts...')
        print(f'-> {TRACTS_2020_URL}')
        gdf = (geodata
            .gdf_from_url(TRACTS_2020_URL, verify=False, limit_to_region=True)
            .rename(columns={
                'STATEFP': 'statefp',
                'COUNTYFP': 'countyfp',
                'TRACTCE': 'tractce',
                'GEOID': 'geoid',
                'NAME': 'name',
                'NAMELSAD': 'namelsad',
                'MTFCC': 'mtfcc',
                'FUNCSTAT': 'funcstat',
                'ALAND': 'aland',
                'AWATER': 'awater',
                'INTPTLAT': 'intptlat',
                'INTPTLON': 'intptlon',
            })
            .assign(version='2020')
        )

        gdf['geoid'] = gdf['geoid'].astype(str).str.zfill(11)

        return gdf[[
            'geoid', 'statefp', 'countyfp', 'tractce', 'name', 'namelsad',
            'mtfcc', 'funcstat', 'aland', 'awater', 'intptlat', 'intptlon',
            'geometry', 'version'
        ]]

    def load_2010_tracts(self) -> pd.DataFrame:
        print('\nLoading 2010 tracts...')
        print(f'-> {TRACTS_2010_URL}')
        gdf = (geodata
            .gdf_from_url(TRACTS_2010_URL, verify=False, limit_to_region=True)
            .rename(columns={
                'STATEFP10': 'statefp',
                'COUNTYFP10': 'countyfp',
                'TRACTCE10': 'tractce',
                'GEOID10': 'geoid',
                'NAME10': 'name',
                'NAMELSAD10': 'namelsad',
                'MTFCC10': 'mtfcc',
                'FUNCSTAT10': 'funcstat',
                'ALAND10': 'aland',
                'AWATER10': 'awater',
                'INTPTLAT10': 'intptlat',
                'INTPTLON10': 'intptlon',
            })
            .assign(version='2010')
        )

        gdf['geoid'] = gdf['geoid'].astype(str).str.zfill(11)

        return gdf[[
            'geoid', 'statefp', 'countyfp', 'tractce', 'name', 'namelsad',
            'mtfcc', 'funcstat', 'aland', 'awater', 'intptlat', 'intptlon',
            'geometry', 'version'
        ]]

    def load_ruca_2020(self) -> pd.DataFrame:
        print('\nLoading 2020 Rural/Urban Communting Areas...')
        print(f'-> {RUCA_2020_URL}')
        df = (pd
            .read_csv(RUCA_2020_URL,
                dtype=str,
                encoding='windows-1252'
            )
            .rename(columns={
                'TractFIPS20': 'geoid',
                'PrimaryRUCA': 'ruca_code',
                'UrbanCoreType': 'ruca_urban_core_type',
                'UrbanAreaName20': 'ruca_urban_area',
                'PrimaryDestinationName': 'ruca_primary_destination',
            })
        )

        df['geoid'] = df['geoid'].astype(str).str.zfill(11)
        return df[[
            'geoid', 'ruca_code', 'ruca_urban_core_type',
            'ruca_urban_area', 'ruca_primary_destination',
        ]]

    def load_ruca_2010_xls(self) -> pd.DataFrame:
        print('\nLoading 2010 Rural/Urban Communting Areas...')
        print(f'-> {RUCA_2010_URL}')
        df = (pd
            .read_excel(RUCA_2010_URL,
                header=1, # Load with header at row 2 (zero-indexed), which is the real data header
                dtype=str,
            ).rename(columns={
                'State-County-Tract FIPS Code (lookup by address at http://www.ffiec.gov/Geocode/)': 'geoid',
                'Primary RUCA Code 2010': 'ruca_code_2010',
            })
        )

        df['geoid'] = df['geoid'].astype(str).str.zfill(11)
        return df[['geoid', 'ruca_code_2010']]

    def resolve_ruca_2010(self, ruca_2010: pd.DataFrame, ruca_2010_xls: pd.DataFrame):
        merged = ruca_2010.merge(ruca_2010_xls, on='geoid', how='left')
        merged = merged.rename(columns={'ruca_code': 'ruca_code_2020'})
        merged['ruca_code'] = merged['ruca_code_2020'].fillna(merged['ruca_code_2010'])
        merged['ruca_code_source'] = merged.apply(
            lambda row: '2020' if pd.notna(row['ruca_code_2020']) else '2010',
            axis=1
        )
        merged['ruca_category'] = merged['ruca_code'].apply(self.ruca_category)
        merged['ruca_description'] = merged['ruca_code'].apply(self.ruca_description)
        return merged

    def ruca_description(self, code: str) -> str:
        return {
            '1': 'Metropolitan core',
            '2': 'Metropolitan high commuting',
            '3': 'Metropolitan low commuting',
            '4': 'Micropolitan core',
            '5': 'Micropolitan high commuting',
            '6': 'Micropolitan low commuting',
            '7': 'Small town core',
            '8': 'Small town low commuting',
            '9': 'Small town high commuting',
            '10': 'Rural',
            '99': 'Not Coded',
        }.get(str(code).strip(), 'Unknown')

    def ruca_category(self, code: str) -> str:
        code = str(code).strip()
        if code in {'1', '2', '3'}:
            return 'Metropolitan'
        elif code in {'4', '5', '6'}:
            return 'Micropolitan'
        elif code in {'7', '8', '9'}:
            return 'Small town'
        elif code == '10':
            return 'Rural'
        return 'Unknown'

    def load_sb535_dac(self) -> pd.DataFrame:
        print('\nLoading SB535 DAC...')
        print(f'-> {SB535DAC_URL}')
        gdf = (esri2gpd
            .get(SB535DAC_URL)
            .rename(columns={
                'Tract': 'geoid',
                'DAC_category': 'dac_category',
            })
        )

        gdf['geoid'] = gdf['geoid'].astype(str).str.zfill(11)

        return gdf[['geoid', 'dac_category']]

    def load_tract_relationships(self) -> pd.DataFrame:
        print('\nLoading Tract Relationships...')
        print(f'-> {RELATIONSHIP_URL}')
        if not RELATIONSHIP_CACHE.exists():
            print('\nDownloading file:')
            print(f'-> URL: {RELATIONSHIP_URL}')
            print(f'-> Dest: {RELATIONSHIP_CACHE}\n')
            response = requests.get(RELATIONSHIP_URL, verify=False)
            response.raise_for_status()
            RELATIONSHIP_CACHE.write_text(response.text)
        df = pd.read_csv(RELATIONSHIP_CACHE, dtype=str, sep='|')
        df.columns = df.columns.str.replace('ï»¿', '', regex=False)
        return df

    def clean_json_metadata(self, obj):
        """
        Recursively replaces all float('nan') with None to ensure JSON compatibility.
        """
        if isinstance(obj, dict):
            return {k: self.clean_json_metadata(v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self.clean_json_metadata(v) for v in obj]
        elif isinstance(obj, float) and math.isnan(obj):
            return None
        return obj

    def extract_columns(self, row: pd.Series, prefix: str) -> dict[str, object]:
        """
        Extract columns from a row where the column name starts with `prefix`,
        and return a dictionary with the prefix removed from the keys.
        NaNs are converted to None for JSON-safe metadata.

        Example:
            row = pd.Series({'foo_name': 'Alice', 'foo_age': 30, 'bar_height': 160})
            strip_prefix_from_row(row, 'foo_')
            # {'name': 'Alice', 'age': 30}

        """
        return self.clean_json_metadata({
            col[len(prefix):]: row[col]
            for col in row.index
            if col.startswith(prefix)
        })
