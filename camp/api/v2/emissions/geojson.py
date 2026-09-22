import json

from resticus import generics

from camp.apps.emissions import stats
from camp.apps.emissions.models import Facility
from camp.apps.regions.models import Region
from camp.utils.views import CachedEndpointMixin


class FacilityGeoJSONBase(generics.Endpoint):
    # get() lives on this un-cached base so CachedEndpointMixin.get() on the
    # subclass is the one dispatched to (the pesticides endpoints' pattern).
    def get(self, request):
        scope = stats.resolve_scope(request.GET)
        sector = request.GET.get('sector')
        sector = sector if sector in Facility.Sector.values else None
        rank_map = stats.ranks(scope)
        features = []
        for record in stats.facility_table(scope, sector=sector).filter(facility__point__isnull=False):
            facility = record.facility
            features.append({
                'type': 'Feature',
                'id': facility.sqid,
                'geometry': {
                    'type': 'Point',
                    'coordinates': [round(facility.point.x, 5), round(facility.point.y, 5)],
                },
                'properties': {
                    'id': facility.sqid,
                    'name': facility.name,
                    'sector': facility.get_sector_display(),
                    'value': scope.pollutant.display(record.value),
                    'rank': rank_map.get(record.facility_id),
                },
            })
        return {
            'type': 'FeatureCollection',
            'properties': {
                'year': scope.year,
                'pollutant': scope.pollutant.key,
                'label': scope.pollutant.label,
                'unit': scope.pollutant.unit,
            },
            'features': features,
        }


class FacilityGeoJSON(CachedEndpointMixin, FacilityGeoJSONBase):
    """
    Facilities in scope as GeoJSON points, for the explorer map. Parameters:
    year, county (slug), pollutant, toxics=1, minor=1, sector. `value` is in
    the pollutant's unit (tons/yr, or lbs/yr for toxics).
    """
    cache_timeout = 60 * 60
    cache_key_version = 1


class DistrictListBase(generics.Endpoint):
    def get(self, request):
        districts = (
            Region.objects.filter(type=Region.Type.AIR_DISTRICT, district_facilities__isnull=False)
            .distinct().select_related('boundary').order_by('name')
        )
        features = []
        for district in districts:
            if district.boundary is None:
                continue
            geometry = district.boundary.geometry.simplify(0.002, preserve_topology=True)
            features.append({
                'type': 'Feature',
                'id': district.sqid,
                'geometry': json.loads(geometry.geojson),
                'properties': {'id': district.sqid, 'name': district.name, 'code': district.external_id},
            })
        return {'type': 'FeatureCollection', 'features': features}


class DistrictList(CachedEndpointMixin, DistrictListBase):
    """Outlines of the air districts that regulate imported facilities, as GeoJSON, simplified for display."""
    cache_timeout = 60 * 60 * 24
    cache_key_version = 1
