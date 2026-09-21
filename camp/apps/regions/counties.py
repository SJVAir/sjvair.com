"""
The counties SJVAir covers, as known to the rest of the codebase.

The list itself is `settings.SJVAIR_COUNTIES`. County geometry lives in the
county `Region` rows (imported by `import_counties`); this module carries the
name forms and the point lookup that reads those rows.
"""

from django.conf import settings

# Short names, as stored on Monitor.county: 'Fresno', 'Kern', ...
COUNTY_NAMES = sorted(settings.SJVAIR_COUNTIES)

# Region names: 'Fresno County', 'Kern County', ...
SJV_COUNTIES = {f'{name} County' for name in COUNTY_NAMES}

# Slug -> short name: 'san_joaquin' -> 'San Joaquin'
COUNTY_KEYS = {name.lower().replace(' ', '_'): name for name in COUNTY_NAMES}


def county_name(point, default=''):
    """Short name of the covered county Region containing `point`, or `default`."""
    from camp.apps.regions.models import Region

    if point is None:
        return default
    name = (Region.objects.counties()
        .filter(boundary__geometry__contains=point)
        .values_list('name', flat=True)
        .first())
    return name.removesuffix(' County') if name else default
