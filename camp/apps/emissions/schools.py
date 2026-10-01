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
from django.db import connection

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


# An area page's Schools tab: every school and child-care center in the area
# with what's near it -- permitted facilities within 1,000 ft and 1/4 mile
# (the facility page's two distances), active or idle oil and gas wells
# within 3,200 ft (wells.HPZ_FEET, the health protection zone) and dairies
# within a mile.

DAIRY_MILES = 1
METERS_PER_FOOT = 0.3048
METERS_PER_MILE = 1609.344
SITE_SORTS = ('name', '-name', 'notice', '-notice', 'quarter', '-quarter', 'value', '-value', 'wells', '-wells', 'dairies', '-dairies')
SITE_TYPES = {'school': (Location.Type.PUBLIC_SCHOOL, Location.Type.PRIVATE_SCHOOL), 'child-care': (Location.Type.CHILD_CARE,)}


def _pairs(table, extra_where, meters, degrees, params=()):
    """
    (location pk, other pk, metres) for every location with a row of `table`
    within `meters`: the bbox (`degrees` of ST_Expand) lets the GiST index
    find the candidates, the geography distance decides.
    """
    sql = f"""
        SELECT l.id, o.id, ST_Distance(l.point::geography, o.point::geography)
        FROM {Location._meta.db_table} l
        JOIN {table} o ON o.point && ST_Expand(l.point, %s)
        WHERE o.point IS NOT NULL {extra_where}
          AND ST_DWithin(l.point::geography, o.point::geography, %s)
    """
    with connection.cursor() as cursor:
        cursor.execute(sql, [degrees, *params, meters])
        return cursor.fetchall()


def site_index():
    """
    {Location pk: {'notice': [facility pk], 'quarter': [facility pk],
    'dairies': n, 'wells': n}} for the Valley's schools and child-care
    centers with anything near them. 'quarter' includes 'notice'. Facilities
    count only where their point is one worth measuring from (shows_for);
    dairies, where CADD counted a herd in its latest year. Cached a day under
    the facilities', dairies' and wells' generations.
    """
    from camp.apps.emissions import dairies, stats, wells
    from camp.apps.emissions.models import Dairy, DairyHerd

    def compute():
        index = {}

        def entry(pk):
            return index.setdefault(pk, {'notice': [], 'quarter': [], 'dairies': 0, 'wells': 0})

        sources = list(Facility.TRUSTED_POINT_SOURCES)
        placeholders = ', '.join(['%s'] * len(sources))
        pairs = _pairs(Facility._meta.db_table, f'AND o.point_source IN ({placeholders})',
                       QUARTER_MILE_FT * METERS_PER_FOOT, 0.008, sources)
        candidates = Facility.objects.in_bulk({facility for _, facility, _ in pairs})
        shown = {pk for pk, facility in candidates.items() if shows_for(facility)}
        for location, facility, meters in sorted(pairs, key=lambda pair: pair[2]):
            if facility not in shown:
                continue
            row = entry(location)
            row['quarter'].append(facility)
            if meters <= NOTICE_FT * METERS_PER_FOOT:
                row['notice'].append(facility)

        herds = set(DairyHerd.objects.filter(dairies.COUNTED, year=dairies.latest_year()).values_list('dairy_id', flat=True))
        for location, dairy, _ in _pairs(Dairy._meta.db_table, '', DAIRY_MILES * METERS_PER_MILE, 0.025):
            if dairy in herds:
                entry(location)['dairies'] += 1

        for location, count in wells.locations_near_wells().items():
            entry(location)['wells'] = count
        return index

    cache_key = f'emissions:v{CACHE_VERSION}:sites:s{stats.generation()}:d{dairies.generation()}:w{wells.generation()}'
    return cache.get_or_set(cache_key, compute, CACHE_TIMEOUT)


def site_filters(get):
    """The Schools tab's filters from a query string, validated: q, type ('school' or 'child-care'), near (a flag) and sort."""
    kind = get.get('type')
    sort = get.get('sort')
    return {
        'q': (get.get('q') or '').strip() or None,
        'type': kind if kind in SITE_TYPES else None,
        'near': get.get('near') == '1',
        'sort': sort if sort in SITE_SORTS else '-quarter',
    }


def area_sites(area, scope, *, q=None, type=None, near=False, sort='-quarter'):
    """
    The area's schools and child-care centers (wells.location_q), each a dict:
    sqid, name, type, type_label, lat, lng, notice and quarter (facility
    counts), value (the scope's pollutant from the facilities within 1/4
    mile, None with none of them reporting), wells, dairies -- facilities
    only those in the scope, as the rest of the page counts them -- filtered and
    sorted for the Schools tab's table, map and CSV.
    """
    from camp.apps.emissions import stats, wells

    index = site_index()
    places = Location.objects.filter(wells.location_q(area)).only('pk', 'sqid', 'name', 'type', 'point')
    if q:
        places = places.filter(name__icontains=q)
    if type:
        places = places.filter(type__in=SITE_TYPES[type])
    empty = {'notice': [], 'quarter': [], 'dairies': 0, 'wells': 0}
    places = [(place, index.get(place.pk, empty)) for place in places]
    # Facilities count as the rest of the page does: those in the scope (its
    # year, minor sources only when included), each with its value.
    nearby_ids = {facility for _, near_it in places for facility in near_it['quarter']}
    values = dict(
        stats.facility_table(scope).filter(facility_id__in=nearby_ids).values_list('facility_id', 'value')
    ) if nearby_ids else {}
    rows = []
    for place, near_it in places:
        quarter = [facility for facility in near_it['quarter'] if facility in values]
        notice = [facility for facility in near_it['notice'] if facility in values]
        reported = [values[facility] for facility in quarter if values[facility]]
        row = {
            'sqid': place.sqid, 'name': place.name, 'type': place.type, 'type_label': str(Location.SHORT_TYPES[place.type]),
            'lat': place.point.y, 'lng': place.point.x,
            'notice': len(notice), 'quarter': len(quarter),
            'value': sum(reported) if reported else None,
            'wells': near_it['wells'], 'dairies': near_it['dairies'],
        }
        if near and not (row['quarter'] or row['wells'] or row['dairies']):
            continue
        rows.append(row)
    # By name within ties; a site with nothing to sort by (no reported value) goes last either way.
    field = sort.lstrip('-')
    descending = sort.startswith('-')
    rows.sort(key=lambda row: row['name'], reverse=descending and field == 'name')
    if field != 'name':
        rows.sort(key=lambda row: row[field] or 0, reverse=descending)
        rows.sort(key=lambda row: row[field] is None)
    return rows


def site_summary(rows):
    """The Schools tab's stat row from area_sites() rows (unfiltered): sites by kind, and how many have each source near."""
    return {
        'schools': sum(1 for row in rows if row['type'] != Location.Type.CHILD_CARE),
        'child_care': sum(1 for row in rows if row['type'] == Location.Type.CHILD_CARE),
        'quarter': sum(1 for row in rows if row['quarter']),
        'notice': sum(1 for row in rows if row['notice']),
        'wells': sum(1 for row in rows if row['wells']),
        'dairies': sum(1 for row in rows if row['dairies']),
    }


def sites_geojson(rows):
    """The sites as the facility map's `nearby` dots, each with a line saying what's near it for its popup."""
    features = []
    for row in rows:
        near_it = []
        if row['quarter']:
            near_it.append(f"{row['quarter']} facilit{'y' if row['quarter'] == 1 else 'ies'} within ¼ mile")
        if row['wells']:
            near_it.append(f"{row['wells']} well{'' if row['wells'] == 1 else 's'} within 3,200 ft")
        if row['dairies']:
            near_it.append(f"{row['dairies']} dair{'y' if row['dairies'] == 1 else 'ies'} within 1 mile")
        features.append({
            'type': 'Feature',
            'geometry': {'type': 'Point', 'coordinates': [round(row['lng'], 5), round(row['lat'], 5)]},
            'properties': {'name': row['name'], 'type_label': row['type_label'], 'summary': ' · '.join(near_it) or 'Nothing we track nearby'},
        })
    return {'type': 'FeatureCollection', 'features': features}
