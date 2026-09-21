"""
Schools and child care facilities as GeoJSON points for the explorer maps.
Points come from `regions.Location`; the per-source details (grade span,
capacity) live in its `metadata`, which differs by source.
"""
import json

from django.contrib.gis.geos import Polygon

from resticus import generics

from camp.apps.regions.models import Location
from camp.utils.views import CachedEndpointMixin

from .sections import bad_request, parse_bbox

# The map only asks for locations from zoom 9 up, where the viewport is well
# under a degree. The cap keeps a hand-built request from serializing every
# school and day care in the state.
MAX_BBOX_DEGREES = 3.0


def grade_span(metadata):
    """
    'K-6' from whichever keys this location's source filled in: CDE public
    schools carry `grades`, private schools `grade_low`/`grade_high`.
    None when the source carried neither.
    """
    grades = (metadata.get('grades') or '').strip()
    if grades:
        return grades
    low = (metadata.get('grade_low') or '').strip()
    high = (metadata.get('grade_high') or '').strip()
    if low and high:
        return low if low == high else f'{low}-{high}'
    return low or high or None


class LocationListBase(generics.Endpoint):
    # See the comment on SectionListBase: the get() implementation lives on
    # this un-cached base so CachedEndpointMixin.get() on LocationList below
    # is the one actually dispatched to.
    def get(self, request):
        params = request.GET
        if not params.get('bbox'):
            return bad_request('bbox is required')
        bbox, error = parse_bbox(params['bbox'])
        if error:
            return bad_request(error)
        west, south, east, north = bbox
        if (east - west) > MAX_BBOX_DEGREES or (north - south) > MAX_BBOX_DEGREES:
            return bad_request('bbox too large; zoom in')

        types = list(Location.Type.values)
        if params.get('type'):
            types = [t.strip() for t in params['type'].split(',') if t.strip()]
            unknown = [t for t in types if t not in Location.Type.values]
            if unknown:
                return bad_request(f'type is invalid: {", ".join(unknown)}')

        locations = (Location.objects
            .filter(type__in=types, point__bboverlaps=Polygon.from_bbox(bbox))
            .select_related('district')
            .order_by('name', 'pk')
        )

        # The explorer's county scope. A bbox always overhangs the county
        # line, so without this a scoped map draws markers whose "within
        # about a mile" figure is from a county the page isn't showing.
        county = (params.get('county') or '').strip()
        if county:
            locations = locations.filter(county__slug=county)

        features = [{
            'type': 'Feature',
            'id': location.sqid,
            'geometry': json.loads(location.point.geojson),
            'properties': {
                'id': location.sqid,
                'name': location.name,
                'type': location.type,
                'type_label': str(location.short_type),
                'address': location.address,
                'city': location.city,
                'district': location.district.name if location.district else None,
                'district_id': location.district.sqid if location.district else None,
                'grade_span': grade_span(location.metadata or {}),
                'capacity': (location.metadata or {}).get('capacity'),
            },
        } for location in locations]
        # A plain dict: CachedEndpointMixin caches it and wraps it in Http200.
        return {'type': 'FeatureCollection', 'features': features}


class LocationList(CachedEndpointMixin, LocationListBase):
    """
    Schools and licensed child care centers as GeoJSON points.

    `bbox=west,south,east,north` is required and may span at most 3 degrees
    on a side. `type` is a comma-separated list of
    `public_school`, `private_school`, `child_care` (default: all three).
    `county` (a county slug) keeps only the locations in that county.
    """
    cache_timeout = 60 * 60 * 24
