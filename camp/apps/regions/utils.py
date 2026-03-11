import tempfile
from pathlib import Path

import pandas as pd
import requests

TRACT_RELATIONSHIP_URL = 'https://www2.census.gov/geo/docs/maps-data/data/rel2020/tract/tab20_tract20_tract10_natl.txt'
TRACT_RELATIONSHIP_CACHE = Path(tempfile.gettempdir()) / 'tract_2010_2020_relationship.txt'


def get_tract_relationships(refresh: bool = False) -> pd.DataFrame:
    """
    Download and cache the Census 2010-to-2020 tract relationship file.

    Returns a DataFrame with GEOID_TRACT_10, GEOID_TRACT_20, and AREALAND_PART columns.
    Used to crosswalk datasets keyed to 2010 tracts onto 2020 tract boundaries.
    """
    if refresh or not TRACT_RELATIONSHIP_CACHE.exists():
        print('Downloading tract relationship file...')
        response = requests.get(TRACT_RELATIONSHIP_URL, verify=False)
        response.raise_for_status()
        TRACT_RELATIONSHIP_CACHE.write_text(response.text)
    else:
        print(f'Using cached relationship file at {TRACT_RELATIONSHIP_CACHE}')

    df = pd.read_csv(TRACT_RELATIONSHIP_CACHE, dtype=str, sep='|')
    print(f'Loaded {len(df):,} rows from relationship file')
    return df
