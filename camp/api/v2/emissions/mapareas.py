"""
The area an explorer map is limited to, from the request: ?region=<sqid> (a
region page's) or ?lat=&lng=&radius= (a near-me page's), widened by
?buffer=1|3 miles (areas.map_shape). Every map endpoint narrows its points to
it, so an area page's map holds only that area's data.
"""
import json

from django.http import Http404
from resticus import generics

from camp.apps.emissions import areas
from camp.apps.emissions.views import AREA_PAGE_TYPES, get_filter_region, radius_area


def get_area(request):
    """(area, error): a RegionArea for ?region=, a RadiusArea for ?lat=&lng=&radius=, (None, None) with neither."""
    sqid = (request.GET.get('region') or '').strip()
    if sqid:
        region = get_filter_region(sqid, types=AREA_PAGE_TYPES)
        if region is None:
            return None, 'region must be the id of a county, community, ZIP code, school district or census tract with a page.'
        return areas.RegionArea(region), None
    if 'lat' in request.GET or 'lng' in request.GET:
        near = radius_area(request.GET)
        if near is None:
            return None, 'lat and lng must be a point, and radius 1, 3 or 5 (miles).'
        return near, None
    return None, None


def get_shape(request):
    """(shape, key, error): the request's area as a geometry (None without one), a cache-key part, or an error message."""
    area, error = get_area(request)
    if error or area is None:
        return None, 'valley', error
    buffer = areas.buffer_param(request.GET)
    return areas.map_shape(area, buffer), f'{area.key}:{buffer}', None


class AreaShape(generics.Endpoint):
    """
    An area page's map edge as GeoJSON: the region's boundary or the near-me
    circle, widened by ?buffer=1|3 miles, for the map to draw when it reaches
    past the area. 404 without an area.
    """

    def get(self, request):
        shape, _, error = get_shape(request)
        if error or shape is None:
            raise Http404(error or 'No area.')
        return {'type': 'Feature', 'properties': {'buffer': areas.buffer_param(request.GET)}, 'geometry': json.loads(shape.json)}
