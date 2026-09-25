"""
Total population (ACS 5-year, table B01003) for counties, ZIP areas (ZCTAs)
and 2020 census tracts, stored as Region.metadata['population']. One Census
API request per geography. Requires a (free) Census API key, passed as `key`
to `fetch`; the import_population command sources it from settings.CENSUS_API_KEY.
"""
import requests

from django.db import transaction

from camp.apps.regions.models import Region

ACS_YEAR = 2024
URL = 'https://api.census.gov/data/{year}/acs/acs5'
VARIABLE = 'B01003_001E'
STATE = '06'
# Region type -> (Census `for`/`in` parameters, columns that make the GEOID).
GEOGRAPHIES = {
    'county': (Region.Type.COUNTY, {'for': 'county:*', 'in': f'state:{STATE}'}, ('state', 'county')),
    'zipcode': (Region.Type.ZIPCODE, {'for': 'zip code tabulation area:*'}, ('zip code tabulation area',)),
    'tract': (Region.Type.TRACT, {'for': 'tract:*', 'in': [f'state:{STATE}', 'county:*']}, ('state', 'county', 'tract')),
}


class CensusAPIError(Exception):
    pass


def fetch(geography, year=ACS_YEAR, key=None):
    _, params, geoid_columns = GEOGRAPHIES[geography]
    query = {'get': VARIABLE, **params}
    if key:
        query['key'] = key
    response = requests.get(URL.format(year=year), params=query, timeout=120)
    response.raise_for_status()
    try:
        header, *rows = response.json()
    except ValueError:
        # The Census API answers a missing or bad key with an HTML page
        # rather than an error status, so a JSON parse failure here almost
        # always means the key, not the network or the year.
        raise CensusAPIError(
            'The Census API needs a key: set CENSUS_API_KEY '
            '(free at https://api.census.gov/data/key_signup.html)'
        )
    value_at = header.index(VARIABLE)
    geoid_at = [header.index(column) for column in geoid_columns]
    counts = {}
    for row in rows:
        try:
            counts[''.join(row[i] for i in geoid_at)] = int(row[value_at])
        except (TypeError, ValueError):
            continue  # Census marks suppressed values with negative sentinels or nulls.
    return counts


def apply(region_type, counts):
    """Write each current region's population; returns (updated, missing from the ACS)."""
    updated = missing = 0
    with transaction.atomic():
        for region in Region.objects.filter(type=region_type).current_vintage():
            value = counts.get(region.external_id or '')
            if value is None or value < 0:
                missing += 1
                continue
            region.metadata = {**(region.metadata or {}), 'population': value}
            region.save(update_fields=['metadata'])
            updated += 1
    return updated, missing
