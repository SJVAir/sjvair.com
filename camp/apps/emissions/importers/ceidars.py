"""
Fetching and parsing CARB's CEIDARS facility inventory CSVs.

No air basin or district filter in the URLs: a request returns the whole
county, so a county that spans two districts (Kern: SJU and KER) comes back
complete. Districts assign FACIDs independently, so rows are identified by
(DIS, FACID) everywhere below; toxics come from facdet_url().
"""

import io
import re
import time

import pandas as pd
import requests

BASE_URL = 'https://www.arb.ca.gov/app/emsinv/iframe/facinfo'

# CARB column -> EmissionsRecord field. PMT is total particulate matter.
CRITERIA_COLS = {
    'TOGT': 'tog', 'ROGT': 'rog', 'COT': 'co',
    'NOXT': 'nox', 'SOXT': 'sox', 'PMT': 'pm', 'PM10T': 'pm10',
}

TOXICS_COLS = {
    'TS': 'total_score', 'HRA': 'hra',
    'CHINDEX': 'chindex', 'AHINDEX': 'ahindex',
}

MERGE_KEYS = ['CO', 'AB', 'FACID', 'DIS', 'FNAME', 'FSTREET', 'FCITY', 'FZIP', 'FSIC']

# Known corrections for CEIDARS city name variants.
# Keys are uppercase raw values; values are the corrected uppercase form
# used for region lookup. Strip-CA-suffix handling is done separately.
CITY_CORRECTIONS = {
    'AWAHNEE': 'AHWAHNEE',
    'BAKERSIFLED': 'BAKERSFIELD',
    'KETTLEMAN': 'KETTLEMAN CITY',
    'LAKE OF THE WDS': 'LAKE OF THE WOODS',
    'LEGRAND': 'LE GRAND',
    'LEMONCOVE': 'LEMON COVE',
    'MC FARLAND': 'MCFARLAND',
    "O'NEILS": "O'NEALS",
    'ONEALS': "O'NEALS",
    'PINE MTN CLUB': 'PINE MOUNTAIN CLUB',
    'PORTERVILE': 'PORTERVILLE',
    'TRANQUILITY': 'TRANQUILLITY',
}

# Patterns that indicate a value is not a city name (county strings,
# GPS coordinates, descriptive strings, etc.) -- these resolve to None.
_NON_CITY_RE = re.compile(
    r'county|sjvapcd|valley$|national|nat park|\bnf\b|cyn\b|site near|'
    r'mi n/o|w/o\s|west of|skyline|tejon ranch|terminus|pampa peak|'
    r'las yeguas|western fresno|& kings|sec\s*\d|\bt\d+s\b',
    re.IGNORECASE,
)

_STRIP_CA_RE = re.compile(r',?\s*CA$', re.IGNORECASE)


def normalize_city(raw, city_lookup):
    """
    Normalize a raw CEIDARS city string and return a matching Region or None.

    city_lookup: dict mapping uppercase city/CDP name -> Region object.
    """
    city = _STRIP_CA_RE.sub('', raw.strip()).strip().upper()
    if not city or _NON_CITY_RE.search(city):
        return None
    city = CITY_CORRECTIONS.get(city, city)
    return city_lookup.get(city)


# CARB's DIS code -> the air basin its facilities are in (the facdet CSV's
# ab_ parameter is required; Kern's two districts sit in two basins).
AIR_BASINS = {'SJU': 'SJV', 'KER': 'MD'}


def csv_url(kind, year, county_code):
    """kind is 'faccrit' (criteria) or 'factox' (the Hot Spots summary columns)."""
    return f'{BASE_URL}/{kind}_output.csv?dbyr={year}&co_={county_code}'


def facdet_url(year, county_code, district_code, facid):
    """
    One facility's toxics for one year: every pollutant it reported, with
    CARB's pollutant id and pounds per year (columns FACID, CO, AB, DIS,
    POLLUTANT_ID, POLLUTANT, EMISSIONS_LBS_YR). Exhaustive where the
    per-pollutant `showpol` sweep could miss an id.
    """
    basin = AIR_BASINS[district_code]
    return (
        f'{BASE_URL}/facdet_output.csv?&dbyr={year}&ab_={basin}&dis_={district_code}'
        f'&co_={county_code}&sort=T&facid_={facid}'
    )


def fetch_csv(url, retries=5):
    for attempt in range(retries):
        try:
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            try:
                return pd.read_csv(io.StringIO(response.text), dtype=str).fillna('')
            except pd.errors.EmptyDataError:
                return pd.DataFrame()
        except requests.RequestException:
            if attempt == retries - 1:
                raise
            time.sleep((2 ** attempt) * 0.5)


def decimal_or_none(val):
    val = str(val).strip()
    if not val or val.lower() == 'nan':
        return None
    return val


def fetch_county(year, county_code):
    """
    One county and year: the criteria and Hot Spots-summary CSVs outer-joined
    on the facility columns (an empty DataFrame when CARB has nothing).
    Raises requests.RequestException if either request fails. Per-pollutant
    toxics are not here: import_toxics crawls facdet_url() per facility.
    """
    criteria = fetch_csv(csv_url('faccrit', year, county_code))
    toxics = fetch_csv(csv_url('factox', year, county_code))
    frames = [frame for frame in (criteria, toxics) if not frame.empty]
    if not frames:
        return pd.DataFrame()
    if len(frames) == 1:
        return frames[0]
    return pd.merge(criteria, toxics, on=MERGE_KEYS, how='outer', suffixes=('_crit', '_tox')).fillna('')
