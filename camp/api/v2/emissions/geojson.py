import json
from dataclasses import replace

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
        compare = stats.resolve_compare_param(request.GET.get('compare'), scope.year)
        rank_map = stats.ranks(scope)
        field = scope.pollutant.key
        prev_by_facility = {}
        if compare:
            prev_rows = stats.records(replace(scope, year=compare))
            if sector:
                prev_rows = prev_rows.filter(facility__sector=sector)
            prev_by_facility = dict(prev_rows.values_list('facility_id', field))
        features = []
        for record in stats.facility_table(scope, sector=sector).filter(facility__point__isnull=False):
            facility = record.facility
            properties = {
                'id': facility.sqid,
                'name': facility.name,
                'sector': facility.get_sector_display(),
                'value': scope.pollutant.display(record.value),
                'rank': rank_map.get(record.facility_id),
            }
            if compare:
                prev_value = prev_by_facility.get(facility.pk)
                if prev_value is not None:
                    prev_value = scope.pollutant.display(prev_value)
                    if not stats.comparable_baseline(prev_value, scope.pollutant.unit):
                        prev_value = None
                properties['value_prev'] = prev_value
            features.append({
                'type': 'Feature',
                'id': facility.sqid,
                'geometry': {
                    'type': 'Point',
                    'coordinates': [round(facility.point.x, 5), round(facility.point.y, 5)],
                },
                'properties': properties,
            })
        return {
            'type': 'FeatureCollection',
            'properties': {
                'year': scope.year,
                'pollutant': scope.pollutant.key,
                'label': scope.pollutant.label,
                'unit': scope.pollutant.unit,
                'compare': compare or None,
            },
            'features': features,
        }


class FacilityGeoJSON(CachedEndpointMixin, FacilityGeoJSONBase):
    """
    Facilities in scope as GeoJSON points, for the explorer map. Parameters:
    year, county (slug), pollutant, toxics=1, minor=1, sector, and
    ?compare=<year> (a loaded year other than the scope's, ignored
    otherwise) for that year's value under `value_prev`, alongside the
    current one. `value`/`value_prev` are in the pollutant's unit (tons/yr,
    or lbs/yr for toxics). `value_prev` is left out (null) when the compared
    year's value is below stats.SMALL_BASELINE_FLOOR for the unit -- too
    small a baseline for a percent change to mean anything -- and this
    endpoint is always scoped to the current year's facilities, so one that
    closed before it isn't shown even if it reported in the compared year.
    """
    cache_timeout = 60 * 60
    cache_key_version = 2


class DistrictListBase(generics.Endpoint):
    def get(self, request):
        districts = (
            Region.objects.filter(type=Region.Type.AIR_DISTRICT, pk__in=Facility.objects.values('air_district_id'))
            .select_related('boundary').order_by('name')
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
