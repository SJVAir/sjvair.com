"""
What every interactive map's container needs from the server: the MapTiler
key and style, the covered counties' bounds (the frame a map opens on when
its page doesn't frame it), and the chrome it asks for. Rendered by
templates/maps/includes/map.html; read by assets/js/maps/shell.js.

Not `maps.py`: that module is the matplotlib static-map renderer.
"""

from django.conf import settings
from django.contrib.gis.db.models import Extent
from django.core.cache import cache

from camp.apps.regions.models import Region

MAP_STYLE = 'dataviz'
BOUNDS_CACHE_KEY = 'maps:v1:bounds'
BOUNDS_CACHE_TIMEOUT = 60 * 60 * 24


def covered_bounds():
    """'west,south,east,north' around the covered counties; '' when none are loaded."""
    bounds = cache.get(BOUNDS_CACHE_KEY)
    if bounds is not None:
        return bounds
    extent = Region.objects.counties().aggregate(extent=Extent('boundary__geometry'))['extent']
    bounds = ','.join(f'{value:.4f}' for value in extent) if extent else ''
    # An environment that renders a map before `import_counties` has run has
    # no extent yet; caching that would serve empty bounds for a day after
    # the counties land.
    if bounds:
        cache.set(BOUNDS_CACHE_KEY, bounds, BOUNDS_CACHE_TIMEOUT)
    return bounds


def map_config(container_class, *, data, features, toolbar_template=None, options_template=None,
               legend_template=None, container_id='', compact=False):
    """
    The dict `maps/includes/map.html` renders as `map`. `data` maps
    data-attribute names (hyphenated, without `data-`) to values; the shared
    keys are filled in unless the caller set them, and every value becomes a
    string (None -> '').
    """
    shared = {
        'maptiler-key': settings.MAPTILER_API_KEY,
        'style': MAP_STYLE,
        # What the chrome below actually renders, for the script to read off
        # the container: the rendered chrome wins over the map module's own
        # spec (assets/js/maps/shell.js), so the two can't drift into a
        # toolbar that's rendered but never unhidden.
        'features': ' '.join(sorted(name for name, on in features.items() if on)),
    }
    # Only looked up when the caller doesn't frame the map itself.
    if 'bounds' not in data:
        shared['bounds'] = covered_bounds()
    merged = {**shared, **data}
    return {
        'container_class': container_class,
        'container_id': container_id,
        'data': {key: '' if value is None else str(value) for key, value in merged.items()},
        'features': features,
        'toolbar_template': toolbar_template,
        'options_template': options_template,
        'legend_template': legend_template,
        'compact': compact,
    }
