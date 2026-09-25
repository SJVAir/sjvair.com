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
        compare = stats.resolve_compare_param(request.GET.get('compare'), scope.year)
        return areas.area_values(scope, level, sector, compare)


class AreaValues(CachedEndpointMixin, AreaValuesBase):
    """
    Per-area emissions for the map's Areas view: ?level= (county, zipcode,
    tract; required) plus the explorer scope (year, county, pollutant,
    toxics=1, minor=1), sector, and ?compare=<year> (a loaded year other
    than the scope's, ignored otherwise) for the same totals and rates from
    that year, under a `_prev` suffix. Numbers only; shapes come from
    /api/2.0/regions/geojson/?type=<level>&simplify=1, joined on `id`.
    """
    cache_timeout = 60 * 60
    cache_key_version = 2
