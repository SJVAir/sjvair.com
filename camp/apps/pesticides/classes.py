"""
Valley-wide class breaks for the section and township maps (`classes=1`).

Every section (or township) the rollup has for the request's year, month and value
filters is ranked together, so a color means the same range anywhere on the map. The
spatial scope (bbox, radius, region, county) never changes the classes. The figures are
the ones the features carry, from the same counting path, so a feature's value always
falls in the classes.
"""
import hashlib
import json

from camp.apps.pesticides import maps, stats
from camp.apps.pesticides.models import PesticideUseRollup

FIGURES = ('lbs_chemical', 'acres_treated', 'applications')
# The params the classes depend on; ids hash by pk. Anything else (bbox, radius,
# region, county, compare, geometry) is spatial or presentational and doesn't.
VALUE_PARAMS = (
    'month', 'chemical', 'product', 'commodity', 'chemical_id', 'product_id', 'commodity_id',
    'method', 'aerial_ground', 'narrow', 'concern', 'category', 'iarc_group',
)
LEVELS = ('section', 'township')


def breaks_for(values):
    """`{'breaks', 'min'}` over `values` ({key: figure}); zero is no data and left out."""
    positive = {key: value for key, value in values.items() if value and value > 0}
    return {
        'breaks': maps.quantile_classes(positive).breaks,
        'min': min(positive.values()) if positive else None,
    }


def _hashable(value):
    return getattr(value, 'pk', value)


def cache_key(level, year, all_years, params, filters):
    """The classes' key: the level, the year, and a hash of the value filters (cleaned ones from `filters`, the rest raw)."""
    values = {}
    for name in VALUE_PARAMS:
        if name in filters:
            values[name] = _hashable(filters[name])
        elif params.get(name):
            values[name] = params.get(name)
    digest = hashlib.md5(json.dumps(values, sort_keys=True, default=str).encode()).hexdigest()
    return stats.all_years_key('classes', level, stats.ALL_YEARS if all_years else year, digest)


def without_county(params):
    """`params` minus `county`: apply_filters() would narrow the population to it."""
    params = params.copy()
    params.pop('county', None)
    return params


def build_classes(level, year, all_years, params, filters):
    """The uncached classes: `{figure: breaks_for(...)}` over every section or township of the year."""
    # Lazily: the sections endpoint module imports this one.
    from camp.api.v2.pesticides import sections

    params = without_county(params)
    if sections.section_totals_available(params):
        by_section = sections.section_totals(None, year, all_years)
    else:
        rows = stats.in_year(PesticideUseRollup.objects.filter(mtrs__isnull=False), year, all_years)
        rows, _ = sections.apply_filters(rows, params, filters)
        by_section = sections.section_figures(rows, params, filters)
    by_key = stats.fold_townships(by_section) if level == 'township' else by_section
    return {figure: breaks_for({key: row[figure] or 0 for key, row in by_key.items()}) for figure in FIGURES}


def valley_classes(level, year, all_years, params, filters=None):
    """
    The classes for `level` ('section' or 'township'), cached under the pesticide data
    version (an import retires them). `filters` are the cleaned map filters; when not
    given they're parsed from `params`.
    """
    if level not in LEVELS:
        raise ValueError(f'level must be one of {LEVELS}')
    if filters is None:
        from camp.api.v2.pesticides.sections import ROLLUP_MAP_FILTERS, parse_map_filters
        filters, _ = parse_map_filters(params, ROLLUP_MAP_FILTERS)
    return stats.cached(
        cache_key(level, year, all_years, params, filters),
        lambda: build_classes(level, year, all_years, params, filters),
    )
