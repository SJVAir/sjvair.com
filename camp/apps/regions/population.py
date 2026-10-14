"""
Total population (ACS 5-year, table B01003) for counties, ZIP areas (ZCTAs),
2020 census tracts, Census places (cities and CDPs) and school districts
(matched on their federal ID), stored as Region.metadata['population']. One Census
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
# Geography -> (region type or types, Census `for`/`in` parameters, columns
# that make the GEOID). A Census place is a city or a CDP.
GEOGRAPHIES = {
    'county': (Region.Type.COUNTY, {'for': 'county:*', 'in': f'state:{STATE}'}, ('state', 'county')),
    'zipcode': (Region.Type.ZIPCODE, {'for': 'zip code tabulation area:*'}, ('zip code tabulation area',)),
    'tract': (Region.Type.TRACT, {'for': 'tract:*', 'in': f'state:{STATE} county:*'}, ('state', 'county', 'tract')),
    'place': ((Region.Type.CITY, Region.Type.CDP), {'for': 'place:*', 'in': f'state:{STATE}'}, ('state', 'place')),
}


class CensusAPIError(Exception):
    pass


# The ACS splits school districts three ways; a district's metadata['fed_id']
# (its NCES ID, state + district code) is the GEOID in whichever it's in.
SCHOOL_DISTRICT_LEVELS = ('elementary', 'secondary', 'unified')


def fetch(geography, year=ACS_YEAR, key=None):
    _, params, geoid_columns = GEOGRAPHIES[geography]
    return _fetch(params, geoid_columns, year, key)


def fetch_school_districts(year=ACS_YEAR, key=None):
    """Every school district's population, the three ACS levels merged, by GEOID."""
    counts = {}
    for level in SCHOOL_DISTRICT_LEVELS:
        geography = f'school district ({level})'
        counts.update(_fetch({'for': f'{geography}:*', 'in': f'state:{STATE}'}, ('state', geography), year, key))
    return counts


def fed_id(region):
    """A school district's GEOID in the ACS."""
    return (region.metadata or {}).get('fed_id')


def _fetch(params, geoid_columns, year, key):
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


def apply(region_types, counts, geoid=None):
    """
    Write each current region's population, for a region type or a tuple of
    them; returns (updated, missing from the ACS). `geoid` takes a region and
    returns its key in `counts` (default: its external_id).
    """
    if isinstance(region_types, str):
        region_types = (region_types,)
    updated = missing = 0
    with transaction.atomic():
        for region in Region.objects.filter(type__in=region_types).current_vintage():
            value = counts.get((geoid(region) if geoid else region.external_id) or '')
            if value is None or value < 0:
                missing += 1
                continue
            region.metadata = {**(region.metadata or {}), 'population': value}
            region.save(update_fields=['metadata'])
            updated += 1
    return updated, missing

