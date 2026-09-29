from django.http import Http404
from resticus import generics

from camp.apps.emissions import wells
from camp.apps.emissions.models import Well
from camp.utils.views import CachedEndpointMixin


class WellsCachedEndpointMixin(CachedEndpointMixin):
    """Response caching that a re-import (wells.clear_caches) invalidates."""

    def get_view_cache_key(self):
        return f'{super().get_view_cache_key()}|g:{wells.generation()}'


class WellGeoJSONBase(generics.Endpoint):
    # get() lives on this un-cached base so the mixin's get() on the subclass
    # is the one dispatched to (the explorer endpoints' pattern).
    def get(self, request):
        features = []
        for well in Well.objects.only('id', 'status', 'in_hpz', 'point').order_by('pk').iterator(chunk_size=5000):
            features.append({
                'type': 'Feature',
                'id': well.sqid,
                'geometry': {'type': 'Point', 'coordinates': [round(well.point.x, 5), round(well.point.y, 5)]},
                'properties': {'id': well.sqid, 's': well.status, 'h': 1 if well.in_hpz == Well.HPZ.VERIFIED else 0},
            })
        stamp = wells.stamp()
        return {
            'type': 'FeatureCollection',
            'properties': {'wells': len(features), 'imported': stamp.imported_at.date().isoformat() if stamp else None},
            'features': features,
        }


class WellGeoJSON(WellsCachedEndpointMixin, WellGeoJSONBase):
    """
    Every active, idle or new oil and gas well CalGEM lists in the covered
    counties, as GeoJSON points for the facility map's wells overlay. Lean
    by design (about 66,000 points): properties are `id` (for the detail
    endpoint), `s` (Active / Idle / New) and `h` (1 inside a verified health
    protection zone). Source: CalGEM WellSTAR (CC-BY); a regulatory record,
    not emissions. Cached a day; a re-import invalidates it.
    """
    cache_timeout = 60 * 60 * 24
    cache_key_version = 1


class WellDetail(generics.Endpoint):
    """One well, for the map popup: lease and number, status, type, operator, field, spud year, HPZ status and its CalGEM record."""

    def get(self, request, sqid):
        well = Well.objects.filter(sqid=sqid).select_related('county').first()
        if well is None:
            raise Http404('No such well.')
        return {
            'id': well.sqid,
            'api': well.api,
            'label': well.label,
            'lease_name': well.lease_name,
            'well_number': well.well_number,
            'status': well.status,
            'well_type': well.well_type_label,
            'operator': well.operator_name,
            'field': well.field_name,
            'county': well.county.name,
            'spud_year': well.spud_date.year if well.spud_date else None,
            'in_hpz': well.in_hpz,
            'directional': well.directional,
            'url': well.calgem_url,
        }
