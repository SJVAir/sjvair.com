"""
CARB's county emission inventory (CEPAM) by emission inventory code (EIC).

Whole-county requests only: the form that splits a county by air district
sits behind bot protection, and the facility inventory is whole-county too.
"""

import csv
import io
import time

import requests

from camp.apps.emissions.models import CountyInventory

# The 2019 SIP inventory: base year 2017, every other year back-cast or
# projected ("grown and controlled"). Change here when CARB publishes a
# newer inventory.
INVENTORY = '2019V104ADJ'
BASE_YEAR = 2017

CSV_URL = 'https://www.arb.ca.gov/app/emsinv/iframe/2021/emsbyeic.csv'

SOURCE_TYPES = {
    'STATIONARY': CountyInventory.SourceType.STATIONARY,
    'AREAWIDE': CountyInventory.SourceType.AREAWIDE,
    'MOBILE': CountyInventory.SourceType.MOBILE,
    'NATURAL+UNPLANNED FIRE EVENT': CountyInventory.SourceType.NATURAL,
}

# CSV column -> CountyInventory field (tons/day)
POLLUTANT_COLUMNS = {
    'TOG': 'tog', 'ROG': 'rog', 'COT': 'co', 'NOX': 'nox', 'SOX': 'sox',
    'PM': 'pm', 'PM10': 'pm10', 'PM2_5': 'pm25',
}
POLLUTANT_FIELDS = tuple(POLLUTANT_COLUMNS.values())


def params(year, county_code):
    return {
        'F_YR': year, 'F_DIV': 0, 'F_SEASON': 'A',
        'SP': INVENTORY, 'SPN': INVENTORY,
        'F_AREA': 'CO', 'F_COAB': '', 'F_CO': county_code,
    }


def fetch_text(year, county_code, retries=5):
    for attempt in range(retries):
        try:
            response = requests.get(CSV_URL, params=params(year, county_code), timeout=60)
            response.raise_for_status()
            return response.text
        except requests.RequestException:
            if attempt == retries - 1:
                raise
            time.sleep((2 ** attempt) * 0.5)


def _float(value):
    value = (value or '').strip()
    return float(value) if value else None


def parse(text, county, year):
    """Unsaved CountyInventory rows; rows without an EIC (blank trailer lines) are skipped."""
    rows = []
    for row in csv.DictReader(io.StringIO(text)):
        eic = (row.get('EIC') or '').strip()
        if not eic:
            continue
        source = (row.get('SRC_TYPE') or '').strip()
        if source not in SOURCE_TYPES:
            raise ValueError(f'Unknown CEPAM source type {source!r} for EIC {eic}')
        rows.append(CountyInventory(
            county=county,
            year=year,
            inventory=INVENTORY,
            source_type=SOURCE_TYPES[source],
            eic=eic,
            summary_name=(row.get('EICSUMN') or '').strip(),
            source_name=(row.get('EICSOUN') or '').strip(),
            material_name=(row.get('EICMATN') or '').strip(),
            subcategory_name=(row.get('EICSUBN') or '').strip(),
            **{field: _float(row.get(column)) for column, field in POLLUTANT_COLUMNS.items()},
        ))
    return rows
