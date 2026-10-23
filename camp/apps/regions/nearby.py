"""
Quick-navigation lists for a place page: the counties, communities, school
districts, and ZIP codes related to a region, shared by both explorers'
"In and around <place>" section (pesticides/place.html,
emissions/area.html). Each explorer owns its own URL tree and its own
cache namespace, so the caller says which `Region.get_*_url()` to link with
and what to key the cache under.
"""
from django.contrib.gis.db.models.functions import Centroid
from django.core.cache import cache

from camp.apps.regions.models import Region

WITHIN_TTL = 60 * 60 * 24


def regions_within(region, *, url_method, cache_prefix, ab617=False):
    """
    {'counties', 'communities', 'school_districts', 'zipcodes', 'any'} for a
    place page: for a county that is everything whose boundary centroid
    falls inside it; for any other region it is everything whose boundary
    overlaps it (sharing only an edge doesn't count), plus the county or
    counties it lies in. The region itself is left out. Communities are the
    cities, urban areas and CDPs, each listed as-is with its `type_label` (a
    town can be both a city and an urban area). Each entry is {'name',
    'url'} (communities add 'type_label'). Cached a day per region and
    `cache_prefix` (so the two explorers, linking to different pages, don't
    share a cached result).

    `url_method` is the name of the `Region` method that builds each
    entry's link ('get_pesticides_url' or 'get_emissions_url'). `ab617`
    (the emissions explorer only -- pesticides has no AB 617 pages) folds
    AB 617 communities into the 'communities' group too, labeled with
    their own `type_label` ("AB 617 Community"): the AB 617 community a
    region overlaps, or, on an AB 617 community's own page, the city/county
    it's in (already covered by 'communities'/'counties').
    """
    # cache_prefix is always paired with the same ab617 value by its caller
    # (region_within passes True, region_within_dairies leaves it False), so
    # the key needn't carry it too.
    key = f'{cache_prefix}:{region.pk}'
    data = cache.get(key)
    if data is not None:
        return data
    geometry = region.boundary.geometry
    kinds = (*Region.COMMUNITY_TYPES, Region.Type.SCHOOL_DISTRICT, Region.Type.ZIPCODE)
    if ab617:
        kinds = (*kinds, Region.Type.AB617_COMMUNITY)
    if region.type == Region.Type.COUNTY:
        rows = (
            Region.objects.filter(type__in=kinds, boundary__isnull=False)
            .annotate(centroid=Centroid('boundary__geometry'))
            .filter(centroid__within=geometry)
        )
    else:
        rows = (
            Region.objects.filter(type__in=kinds + (Region.Type.COUNTY,), boundary__isnull=False)
            .filter(boundary__geometry__intersects=geometry)
            .exclude(boundary__geometry__touches=geometry)
            .exclude(pk=region.pk)
        )
    groups = {'counties': [], 'communities': [], 'school_districts': [], 'zipcodes': []}
    community_order = {region_type: index for index, region_type in enumerate(Region.COMMUNITY_TYPES)}
    for other in sorted(rows, key=lambda other: (other.name, community_order.get(other.type, 0))):
        entry = {
            'name': other.name,
            'url': getattr(other, url_method)(),
        }
        if other.type == Region.Type.COUNTY:
            groups['counties'].append(entry)
        elif other.type == Region.Type.SCHOOL_DISTRICT:
            groups['school_districts'].append(entry)
        elif other.type == Region.Type.ZIPCODE:
            groups['zipcodes'].append(entry)
        else:
            groups['communities'].append({**entry, 'type_label': other.type_label})
    data = {**groups, 'any': any(groups.values())}
    cache.set(key, data, WITHIN_TTL)
    return data


# A town can be mapped twice: as a city or CDP, and as the Census urban area
# that grows around it. Each points to the other.
COUNTERPART_TYPES = {
    Region.Type.CITY: (Region.Type.URBAN_AREA,),
    Region.Type.CDP: (Region.Type.URBAN_AREA,),
    Region.Type.URBAN_AREA: (Region.Type.CITY, Region.Type.CDP),
}


def counterpart(region):
    """
    The same town on the other community layer: a city's or CDP's urban area
    of the same name, or an urban area's city (else CDP). Their boundaries
    must overlap, so a same-named place elsewhere isn't a match. None for any
    other region type, or with no match.
    """
    types = COUNTERPART_TYPES.get(region.type)
    if not types or not region.boundary_id:
        return None
    matches = (
        Region.objects
        .filter(name__iexact=region.name, type__in=types, boundary__geometry__intersects=region.boundary.geometry)
        .exclude(pk=region.pk)
        .select_related('boundary')
    )
    # A city before a CDP when an urban area somehow has both.
    return min(matches, key=lambda match: types.index(match.type), default=None)
