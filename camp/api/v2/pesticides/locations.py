"""
Schools and child care facilities as GeoJSON points for the explorer maps.
Points come from `regions.Location`; the per-source details (grade span,
capacity) live in its `metadata`, which differs by source.
"""
import json

from django.contrib.gis.geos import Point, Polygon
from django.contrib.gis.measure import D

from resticus import generics

from camp.apps.regions.models import Location
from camp.utils.views import CachedEndpointMixin

from .sections import bad_request, clip_shape, parse_bbox

# The map asks for locations from zoom 9 up, and it asks for a bbox padded by
# half a viewport on each side -- on a wide expanded map at that zoom the
# padded box runs to several degrees a side, so a tight cap turned the whole
# layer into a 400. The cap comfortably covers the valley plus that padding.
# The table holds only the valley's sites (~2,800 rows, ~1.5 MB of GeoJSON),
# and a request with no area and no bbox returns all of them, so the cap
# doesn't bound the response size; it only refuses a bbox far bigger than
# any map would send.
MAX_BBOX_DEGREES = 12.0


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


def enrollment(metadata):
    """
    Total enrollment, when the source carried one. CDE public schools nest it
    under `enrollment: {total: ...}`; private schools store a plain number.
    """
    value = metadata.get('enrollment')
    if isinstance(value, dict):
        value = value.get('total')
    return value or None


class LocationListBase(generics.Endpoint):
    # See the comment on SectionListBase: the get() implementation lives on
    # this un-cached base so CachedEndpointMixin.get() on LocationList below
    # is the one actually dispatched to.
    def get(self, request):
        params = request.GET
        # An area (a region, or a point and radius) stands in for the bbox:
        # a place page's Schools tab shows the place's own sites, all of them,
        # at any zoom.
        area, error = self.parse_area(params)
        if error:
            return bad_request(error)
        # Neither an area nor a bbox is the whole valley: every location,
        # still filtered by `type` and `county` below. A blank or
        # whitespace-only bbox counts as none.
        bbox = None
        has_bbox = bool((params.get('bbox') or '').strip())
        if area is None and not has_bbox:
            # Nothing for these to widen: the client meant an area it didn't
            # send, so the whole valley would be the wrong answer.
            if (params.get('radius') or '').strip():
                return bad_request('radius needs lat and lng')
            if (params.get('buffer') or '').strip():
                return bad_request('buffer needs a region')
        if area is None and has_bbox:
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
            .filter(type__in=types)
            .select_related('city', 'school_district')
            .order_by('name', 'pk')
        )
        if area is not None:
            locations = locations.filter(**area)
        elif bbox is not None:
            locations = locations.filter(point__bboverlaps=Polygon.from_bbox(bbox))

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
                # The permanent public code, named as LocationSerializer
                # names it, so a clicked site can be saved as a place.
                'source': location.source,
                'external_id': location.external_id,
                'name': location.name,
                'type': location.type,
                'type_label': str(location.short_type),
                'address': location.address,
                'city': location.get_city() or None,
                'school_district': location.get_school_district(),
                'school_district_id': (location.school_district.sqid
                    if location.school_district_id else None),
                # The district page's real URL, so the popup links straight to
                # it instead of through the slug redirect.
                'school_district_url': location.get_pesticides_url() or None,
                'grade_span': grade_span(location.metadata or {}),
                'enrollment': enrollment(location.metadata or {}),
                'capacity': (location.metadata or {}).get('capacity'),
            },
        } for location in locations]
        # A plain dict: CachedEndpointMixin caches it and wraps it in Http200.
        return {'type': 'FeatureCollection', 'features': features}


    @staticmethod
    def parse_area(params):
        """
        The queryset filter for `region=<sqid>` (a region with a boundary) or
        `lat`, `lng` and `radius` (miles, at most 10), or None for neither;
        and an error message for a bad one.
        """
        sqid = (params.get('region') or '').strip()
        if sqid:
            shape, error = clip_shape(params)
            if error:
                return None, error
            return {'point__within': shape}, None
        if params.get('lat') or params.get('lng'):
            try:
                lat, lng = float(params['lat']), float(params['lng'])
                radius = float(params.get('radius') or 1)
            except (KeyError, TypeError, ValueError):
                return None, 'lat, lng and radius must be numbers'
            if not (-90 <= lat <= 90 and -180 <= lng <= 180) or not (0 < radius <= 10):
                return None, 'lat, lng or radius out of range'
            return {'point__distance_lte': (Point(lng, lat, srid=4326), D(mi=radius))}, None
        return None, None


class LocationList(CachedEndpointMixin, LocationListBase):
    """
    Schools and licensed child care centers as GeoJSON points.

    `bbox=west,south,east,north` may span at most 12 degrees on a side.
    With no bbox and no area (a blank `bbox` counts as none), every location
    in the valley; `radius` or `buffer` without the area they widen is a 400. `type` is a comma-separated list of
    `public_school`, `private_school`, `child_care` (default: all three).
    `county` (a county slug) keeps only the locations in that county.
    Instead of a bbox, `region` (a region's sqid) or `lat`, `lng` and
    `radius` (miles, up to 10) return every location inside that area.
    `region` also takes `buffer=0|1|3|5` to widen the region by that many miles.
    """
    cache_timeout = 60 * 60 * 24
    # v2: the GeoJSON property names changed. v3: `source` and `external_id`
    # added. v4: entries are the encoded body (cache_encoded), not the dict.
    # A day-long cache would keep handing out the old shape long after the
    # deploy.
    cache_key_version = 4
    # The valley-wide answer is ~1.5 MB; a hit serves the cached bytes
    # instead of re-encoding the dict every time. The body is unchanged.
    cache_encoded = True
