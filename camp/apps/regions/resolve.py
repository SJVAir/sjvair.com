"""
Resolving a place (a region by code, or a monitor) from request params, and
the ZIPs and SJVAPCD forecast zone that place falls in.
"""
import hashlib

from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.db.models import Q

from camp.apps.monitors.models import Monitor
from camp.apps.regions.models import Boundary, Region
from camp.apps.regions.querysets import overlap_area

CACHE_TIMEOUT = 60 * 60 * 24
ZIP_MIN_FRACTION = 0.01
# The share of a place's own area a zone must hold for the 'overlap' rule:
# the same 1% floor that drops boundary-disagreement slivers elsewhere.
ZONE_MIN_FRACTION = 0.01

# Every type a point lookup answers for unless asked otherwise. Land use has
# no permanent codes, and MTRS sections are too numerous to be useful.
DEFAULT_LOOKUP_TYPES = tuple(sorted(
    t for t in Region.Type.values if t not in (Region.Type.LAND_USE, Region.Type.MTRS)))
_MISS = object()


class PlaceError(Exception):
    """A bad place request; the message is the 400 text."""


class PlaceNotFound(PlaceError):
    """The place doesn't exist; the message is the 404 text."""


def resolve_place(params):
    """The Region (retired ones included) or public Monitor named by `region_type` + `region`, or `monitor`."""
    monitor_id = (params.get('monitor') or '').strip()
    region_type = (params.get('region_type') or '').strip()
    region_code = (params.get('region') or '').strip()

    if monitor_id and (region_type or region_code):
        raise PlaceError('Give either monitor or region, not both.')
    if bool(region_type) != bool(region_code):
        raise PlaceError('region_type and region go together.')
    if not monitor_id and not region_code:
        raise PlaceError('Give a region (region_type and region) or a monitor.')

    if monitor_id:
        try:
            monitor = Monitor.objects.get_queryset().get_public().get(pk=monitor_id)
        except (Monitor.DoesNotExist, ValidationError, ValueError):
            raise PlaceNotFound(f'No such monitor: {monitor_id}.')
        if monitor.position is None:
            raise PlaceError('Monitor has no location.')
        return monitor

    if region_type == Region.Type.LAND_USE:
        raise PlaceError("Land-use regions can't be looked up by code yet.")
    # all_objects: a retired region's code still answers. The boundary is
    # left unloaded: the zips and zone answers are cached by boundary_id, so
    # a warm request never needs the geometry (see _place_geometry).
    region = Region.all_objects.filter(type=region_type, external_id=region_code).first()
    if region is None:
        raise PlaceNotFound(f'No such region: {region_type} {region_code}.')
    return region


def place_json(place):
    """A resolved place as the public `place` object: its region code, or its monitor id."""
    if isinstance(place, Region):
        return {'region': {'type': place.type, 'external_id': place.external_id, 'name': place.name}}
    return {'monitor': str(place.pk)}


def _place_key(prefix, place):
    if isinstance(place, Region):
        # boundary_id changes when a re-import swaps the boundary, so the key follows it.
        return f'{prefix}:region:{place.pk}:{place.boundary_id}'
    # A moved monitor gets a new key. The position is hashed: its WKT has
    # spaces, which Memcached rejects.
    position = hashlib.md5(place.position.wkb).hexdigest() if place.position else ''
    return f'{prefix}:monitor:{place.pk}:{position}'


def _place_geometry(place):
    """
    The place's geometry: a monitor's point, or a region's boundary (None
    without one). A region's is fetched on its own, only on a cache miss.
    """
    if isinstance(place, Region):
        if place.boundary_id is None:
            return None
        return Boundary.objects.filter(pk=place.boundary_id).values_list('geometry', flat=True).first()
    return place.position


def zips_for(place):
    """
    The current ZIP regions a place covers: a ZIP is itself, a monitor sits in
    at most one, any other region gets the ZIPs with at least 1% of their area
    inside it. The Region objects (not just ids) are cached for 24 hours, so a
    warm call costs no queries.
    """
    if isinstance(place, Region) and place.type == Region.Type.ZIPCODE:
        return [place]

    key = _place_key('zips_for', place)
    cached = cache.get(key)
    if cached is not None:
        return cached

    geometry = _place_geometry(place)
    zips = Region.objects.filter(type=Region.Type.ZIPCODE)
    if geometry is None:
        found = []
    elif isinstance(place, Region):
        found = list(zips.overlapping(geometry, ZIP_MIN_FRACTION).order_by('external_id'))
    else:
        # intersects, not contains: a point on a shared edge is in both
        # (contains would say neither), and the lowest code answers.
        found = list(zips.filter(boundary__geometry__intersects=geometry).order_by('external_id')[:1])
    cache.set(key, found, CACHE_TIMEOUT)
    return found


def _zones():
    """
    The forecast zone regions that exist, keyed by their ZONE_TO_REGION feed
    name, in one query. No boundary is joined: these end up in the cache, and
    a geometry would bloat (or silently fail to store in) Memcached.
    """
    from camp.apps.forecasts.tasks import ZONE_TO_REGION

    wanted = Q()
    for region_type, region_name in ZONE_TO_REGION.values():
        wanted |= Q(type=region_type, name=region_name)
    found = {(r.type, r.name): r for r in Region.objects.filter(wanted)}
    return {feed_name: found[key] for feed_name, key in ZONE_TO_REGION.items() if key in found}


def _zone_for_county(county, zones):
    """
    The zone a county stands for: the one whose feed name leads with the
    county's name ('Kern (SJV Air Basin portion)' and 'Tulare' for Kern and
    Tulare Counties; the other counties are their own zones). Derived from
    ZONE_TO_REGION's keys so there is no second table to keep in step.
    """
    for feed_name, zone in zones.items():
        if f'{feed_name.split(" (")[0]} County' == county.name:
            return zone
    return None


def forecast_zone_for(place):
    """
    The SJVAPCD forecast zone for a place, as (zone, rule): 'county' (a county a zone stands for, itself included),
    'zone' (a custom zone region), 'center' (the zone holding its
    point-on-surface, or a monitor's position), 'overlap' (the zone sharing
    the most area, if that is at least 1% of the place's), else (None, None). Cached for 24 hours.
    """
    key = _place_key('forecast_zone_for', place)
    cached = cache.get(key)
    if cached is not None:
        return cached

    result = _forecast_zone_for(place)
    cache.set(key, result, CACHE_TIMEOUT)
    return result


def _forecast_zone_for(place):
    zones = _zones()
    is_region = isinstance(place, Region)

    if is_region:
        # A county comes first: the six counties that are their own zone read
        # as 'county', like Kern and Tulare, not as 'zone'.
        if place.type == Region.Type.COUNTY:
            zone = _zone_for_county(place, zones)
            if zone is not None:
                return zone, 'county'
        # The zone's own (geometry-free) row, which is what gets cached.
        zone = next((z for z in zones.values() if z.pk == place.pk), None)
        if zone is not None:
            return zone, 'zone'

    geometry = _place_geometry(place)
    if geometry is None or not zones:
        return None, None

    point = geometry.point_on_surface if is_region else geometry
    zone_ids = [zone.pk for zone in zones.values()]
    by_pk = {zone.pk: zone for zone in zones.values()}
    center = (Region.objects.filter(pk__in=zone_ids, boundary__geometry__contains=point)
        .order_by('pk').values_list('pk', flat=True).first())
    if center is not None:
        return by_pk[center], 'center'

    if is_region:
        best = (Region.objects.filter(pk__in=zone_ids, boundary__geometry__intersects=geometry)
            .annotate(shared_area=overlap_area(geometry))
            .filter(shared_area__gt=0, shared_area__gte=ZONE_MIN_FRACTION * geometry.area)
            .order_by('-shared_area', 'pk').values_list('pk', flat=True).first())
        if best is not None:
            return by_pk[best], 'overlap'

    return None, None


def parse_lookup_types(raw):
    """
    The sorted, de-duplicated region types in a comma-separated `type` value;
    the defaults when it is empty.
    """
    types = sorted({t.strip() for t in (raw or '').split(',') if t.strip()})
    if not types:
        return DEFAULT_LOOKUP_TYPES
    for region_type in types:
        if region_type == Region.Type.LAND_USE:
            raise PlaceError("Land-use regions can't be looked up.")
        if region_type not in Region.Type.values:
            raise PlaceError(f'Unknown region type: {region_type}.')
    return tuple(types)


def round_point(lat, lon):
    """Coordinates to 3 decimals (~100 m): all a lookup needs, and a shared cache key."""
    return round(lat, 3), round(lon, 3)


def regions_containing(geometry, types, key):
    """
    The current regions of the given types whose boundary intersects the
    geometry (a point on a shared edge is in both), ordered by type and code,
    as RegionListSerializer dicts. The type filter is part of the one query.
    The dicts (never models: the serializer reads the boundary's bbox) are
    cached for 24 hours, an empty answer too.
    """
    cached = cache.get(key, _MISS)
    if cached is not _MISS:
        return cached

    from camp.api.v2.regions.serializers import RegionListSerializer

    regions = (Region.objects.filter(type__in=types).intersects(geometry)
        .select_related('boundary').order_by('type', 'external_id'))
    found = RegionListSerializer(regions).serialize()
    cache.set(key, found, CACHE_TIMEOUT)
    return found
