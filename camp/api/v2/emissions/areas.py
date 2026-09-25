from resticus import generics, http

from camp.apps.emissions import areas, stats
from camp.apps.emissions.models import Facility
from camp.utils.views import CachedEndpointMixin


class AreaValuesBase(generics.Endpoint):
    # get() lives on this un-cached base so CachedEndpointMixin.get() on the
    # subclass is the one dispatched to (the explorer endpoints' pattern).
    def get(self, request):
        level = request.GET.get('level', '')
        if level not in areas.LEVELS:
            return http.Http400({'error': f"level must be one of {', '.join(areas.LEVELS)}."})
        scope = stats.resolve_scope(request.GET)
        sector = request.GET.get('sector')
        sector = sector if sector in Facility.Sector.values else None
        return areas.area_values(scope, level, sector)


class AreaValues(CachedEndpointMixin, AreaValuesBase):
    """
    Per-area emissions for the map's Areas view: ?level= (county, zipcode,
    tract; required) plus the explorer scope (year, county, pollutant,
    toxics=1, minor=1) and sector. Numbers only; shapes come from
    /api/2.0/regions/geojson/?type=<level>&simplify=1, joined on `id`.
    """
    cache_timeout = 60 * 60
    cache_key_version = 1
