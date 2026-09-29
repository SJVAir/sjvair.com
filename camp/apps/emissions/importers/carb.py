"""
The counties this deployment covers, as CARB knows them.

CARB numbers California's counties alphabetically (Alameda = 1 ... Yuba = 58).
`import_counties` stores that number on each county Region as
`metadata['ca_county_code']`, so coverage is whatever county Regions are
loaded for `settings.SJVAIR_COUNTIES` -- nothing here names a county.
"""

from camp.apps.regions.models import Region


class CountyConfigError(Exception):
    pass


def carb_counties(slug=None):
    """[(carb_county_number, county Region), ...] in name order, optionally one county by slug."""
    counties = Region.objects.counties().order_by('name')
    if slug:
        counties = counties.filter(slug=slug)
        if not counties:
            raise CountyConfigError(f'No covered county with slug {slug!r}.')
    result = []
    for county in counties:
        code = (county.metadata or {}).get('ca_county_code')
        if not code:
            raise CountyConfigError(
                f"{county.name} has no ca_county_code in its metadata; re-run import_counties."
            )
        result.append((int(code), county))
    if not result:
        raise CountyConfigError('No county Regions are loaded; run import_counties.')
    return result


def county_names():
    """{carb_county_number: county name} for the covered counties."""
    return {code: county.name for code, county in carb_counties()}


def parse_years(value):
    """'2024' -> [2024]; '2010-2024' -> [2010, ..., 2024]."""
    value = str(value).strip()
    if '-' in value:
        start, end = (int(part) for part in value.split('-', 1))
        if start > end:
            raise ValueError(f'Year range {value!r} runs backwards.')
        return list(range(start, end + 1))
    return [int(value)]
