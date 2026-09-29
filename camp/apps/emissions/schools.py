"""
Schools and licensed child-care centers near a facility (regions.Location,
from import_locations), for the facility page's "Schools and child care
nearby" card and its map.

Two distances, each with a basis in state law (see the About page):
1,000 ft is where Health & Safety Code 42301.6 requires the district to
notify parents before permitting a source of hazardous air emissions;
1/4 mile is the distance school districts must review before siting a school
(Education Code 17213). Distances are straight lines between map points.

The block is hidden for a facility whose point can't be trusted to be the
site: no point, a point that isn't a Census street match or CARB's own
coordinates, an oil-gas or refining permit grouping (their addresses are
mailing addresses, not well or terminal locations), or an address that
isn't a place at all ("various locations").
"""

import math

from django.contrib.gis.db.models.functions import Distance
from django.contrib.gis.geos import Polygon
from django.contrib.gis.measure import D
from django.core.cache import cache

from camp.apps.emissions import locations
from camp.apps.emissions.models import Facility
from camp.apps.regions.models import Location

NOTICE_FT = 1000
QUARTER_MILE_FT = 1320
FEET_PER_MILE = 5280
MILES_PER_DEGREE = 69.0
# Listed on the card per group; the rest is "and N more".
SHOWN = 10
HIDDEN_SECTORS = (Facility.Sector.OIL_GAS, Facility.Sector.REFINING_FUELS)
CACHE_VERSION = 1
CACHE_TIMEOUT = 60 * 60 * 24


def shows_for(facility):
    """Whether the facility's point is one worth measuring from."""
    if not facility.has_trusted_point:
        return False
    if facility.sector in HIDDEN_SECTORS:
        return False
    return locations.is_geocodable(facility.address or {})


def _bbox(point, miles):
    """A degree bbox around `point`, slightly generous: the GiST prefilter before the exact distance (see pesticides/places.point_area)."""
    dlat = miles / MILES_PER_DEGREE
    dlng = miles / (MILES_PER_DEGREE * max(math.cos(math.radians(point.y)), 0.01))
    box = Polygon.from_bbox((point.x - dlng, point.y - dlat, point.x + dlng, point.y + dlat))
    box.srid = 4326
    return box


def _rows(facility):
    point = facility.point
    if point.srid is None:
        point.srid = 4326
    # Location.point is a geodetic geometry, so Distance/distance_lte run on the
    # sphere and come back in metres; D(ft=...) converts the threshold.
    candidates = (
        Location.objects
        .filter(point__bboverlaps=_bbox(point, QUARTER_MILE_FT / FEET_PER_MILE), point__distance_lte=(point, D(ft=QUARTER_MILE_FT)))
        .annotate(distance=Distance('point', point))
        .order_by('distance', 'name')
    )
    rows = []
    for location in candidates:
        rows.append({
            'sqid': location.sqid,
            'name': location.name,
            'type': location.type,
            'type_label': str(location.short_type),
            'feet': int(round(location.distance.ft)),
            'lat': location.point.y,
            'lng': location.point.x,
        })
    return rows


def near(facility):
    """
    The schools and child care within 1,000 ft and from there to 1/4 mile of
    the facility's point, each list nearest first, or None when the block is
    hidden (shows_for). Cached a day per facility.
    """
    if not shows_for(facility):
        return None

    def compute():
        rows = _rows(facility)
        return {
            'within_1000ft': [row for row in rows if row['feet'] <= NOTICE_FT],
            'within_quarter_mile': [row for row in rows if row['feet'] > NOTICE_FT],
        }

    # Keyed on the point too, so a regeocoded facility isn't served its old distances.
    point = facility.point
    return cache.get_or_set(
        f'emissions:v{CACHE_VERSION}:schools:{facility.pk}:{point.x:.6f},{point.y:.6f}', compute, CACHE_TIMEOUT,
    )


def geojson(result):
    """The listed rows (the first SHOWN of each group) as a FeatureCollection for the facility map's `nearby` source."""
    features = []
    for group, key in (('notice', 'within_1000ft'), ('quarter', 'within_quarter_mile')):
        for row in result[key][:SHOWN]:
            features.append({
                'type': 'Feature',
                'geometry': {'type': 'Point', 'coordinates': [row['lng'], row['lat']]},
                'properties': {'name': row['name'], 'type_label': row['type_label'], 'feet': row['feet'], 'group': group},
            })
    return {'type': 'FeatureCollection', 'features': features}
