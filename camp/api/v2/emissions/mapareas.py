"""
The area an explorer map is limited to, from the request: ?region=<sqid> (a
region page's) or ?lat=&lng=&radius= (a near-me page's), widened by
?buffer=1|3|5 miles (areas.map_shape). Every map endpoint narrows its points to
it, so an area page's map holds only that area's data. The widened edge the
map draws comes from the shared regions detail endpoint (?buffer=).
"""
from camp.apps.emissions import areas
from camp.apps.emissions.views import AREA_PAGE_TYPES, get_filter_region, radius_area
from camp.apps.regions import shapes


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
    # Strict, as the shared regions API is: a bad ?buffer= is an error, not a quiet 0.
    buffer, error = shapes.parse_buffer(request.GET)
    if error:
        return None, None, error
    return areas.map_shape(area, buffer), f'{area.key}:{buffer}', None
