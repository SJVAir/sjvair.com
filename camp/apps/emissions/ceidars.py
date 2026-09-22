"""
Fetching and parsing CARB's CEIDARS facility inventory CSVs.

No air basin or district filter in the URLs: a request returns the whole
county, so a county that spans two districts (Kern: SJU and KER) comes back
complete. Districts assign FACIDs independently, so rows are identified by
(DIS, FACID) everywhere below.
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

# CAS number -> EmissionsRecord field name for named toxic air contaminants.
TOXIC_POLLUTANTS = {
    '75070': 'acetaldehyde',
    '71432': 'benzene',
    '106990': 'butadiene',
    '56235': 'carbon_tetrachloride',
    '18540299': 'chromium_hexavalent',
    '106467': 'dichlorobenzene',
    '50000': 'formaldehyde',
    '75092': 'methylene_chloride',
    '91203': 'naphthalene',
    '127184': 'perchloroethylene',
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


def csv_url(kind, year, county_code, cas_id=None):
    """kind is 'faccrit' (criteria) or 'factox' (toxics)."""
    url = f'{BASE_URL}/{kind}_output.csv?dbyr={year}&co_={county_code}'
    if cas_id:
        url += f'&showpol={cas_id}'
    return url


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


def fetch_county(year, county_code, on_error=None):
    """
    (merged, toxic_ems) for one county and year.

    merged: the criteria and toxics CSVs outer-joined on the facility columns
    (an empty DataFrame when CARB has nothing). toxic_ems: {(DIS, FACID):
    {field: tons}} from the per-pollutant requests; a failed pollutant request
    is reported through on_error(field_name, exc) and skipped. Raises
    requests.RequestException if the criteria or toxics request fails.
    """
    criteria = fetch_csv(csv_url('faccrit', year, county_code))
    toxics = fetch_csv(csv_url('factox', year, county_code))

    toxic_ems = {}
    for cas_id, field_name in TOXIC_POLLUTANTS.items():
        try:
            pollutant = fetch_csv(csv_url('factox', year, county_code, cas_id))
        except requests.RequestException as exc:
            if on_error:
                on_error(field_name, exc)
            continue
        for _, row in pollutant.iterrows():
            key = (row['DIS'], int(row['FACID']))
            toxic_ems.setdefault(key, {})[field_name] = decimal_or_none(row.get('EMS', ''))

    frames = [frame for frame in (criteria, toxics) if not frame.empty]
    if not frames:
        merged = pd.DataFrame()
    elif len(frames) == 1:
        merged = frames[0]
    else:
        merged = pd.merge(
            criteria, toxics,
            on=MERGE_KEYS,
            how='outer',
            suffixes=('_crit', '_tox'),
        ).fillna('')
    return merged, toxic_ems
