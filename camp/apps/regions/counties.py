"""
The San Joaquin Valley counties, as known to the rest of the codebase.

County geometry lives in the county `Region` rows (imported by
`import_counties`); this module only carries the names and the point lookup
that reads those rows.
"""

SJV_COUNTIES = {
    'Fresno County',
    'Kern County',
    'Kings County',
    'Madera County',
    'Merced County',
    'San Joaquin County',
    'Stanislaus County',
    'Tulare County',
}

# Short names, as stored on Monitor.county: 'Fresno', 'Kern', ...
COUNTY_NAMES = sorted(name.removesuffix(' County') for name in SJV_COUNTIES)

# Slug -> short name: 'san_joaquin' -> 'San Joaquin'
COUNTY_KEYS = {name.lower().replace(' ', '_'): name for name in COUNTY_NAMES}


def county_name(point, default=''):
    """Short name of the SJV county Region containing `point`, or `default`."""
    from camp.apps.regions.models import Region

    if point is None:
        return default
    name = (Region.objects.counties()
        .filter(boundary__geometry__contains=point)
        .values_list('name', flat=True)
        .first())
    return name.removesuffix(' County') if name else default
