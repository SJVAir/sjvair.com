import json
import logging
import zlib

from django.core.cache import cache
from django.http import Http404, HttpResponse
from resticus import generics

from camp.apps.emissions import wells
from camp.apps.emissions.models import Well

from .mapareas import get_shape

logger = logging.getLogger(__name__)
STATUSES = [Well.Status.ACTIVE.value, Well.Status.IDLE.value, Well.Status.NEW.value]
# The table filters the cached responses are keyed by (bounded values only).
CACHED_FILTERS = {'status', 'hpz'}


class WellGeoJSON(generics.Endpoint):
    """
    Every active, idle or new oil and gas well CalGEM lists in the covered
    counties, for the facility map's wells overlay: `{"imported": date,
    "statuses": [...], "wells": [[id, lng, lat, status, hpz], ...]}`, where
    `status` indexes `statuses` and `hpz` is 1 inside a verified health
    protection zone. The map rebuilds GeoJSON points from it. Compact on
    purpose: about 66,000 wells. Source: CalGEM WellSTAR (CC-BY); a
    regulatory record, not emissions. Cached a day as compressed bytes (a
    GeoJSON dict of 66,000 features is ~10 MB, over memcached's 1 MB item
    limit, and took seconds to re-encode per request); a re-import
    invalidates it.
    """
    cache_timeout = 60 * 60 * 24

    def get(self, request):
        # An area page's map: only the wells inside its (perhaps widened) area, cached per area.
        shape, area_key, error = get_shape(request)
        if error:
            return HttpResponse(json.dumps({'error': error}), status=400, content_type='application/json')
        # The Oil & gas table's filters, so a filtered table's map shows the same wells.
        filters = {name: value for name, value in wells.table_filters(request.GET).items() if name != 'sort'}
        params = wells.filter_params(filters)
        if params.keys() - CACHED_FILTERS:
            # Free text (a name, an operator, a field) isn't a cache key: memcached
            # rejects spaces and long keys, and every spelling would be its own entry.
            # Narrowed that far, the query is quick uncached.
            return HttpResponse(self.payload(shape, filters), content_type='application/json')
        # Status and HPZ are a handful of fixed values: cached per area as the unfiltered list is.
        key = wells.key('geojson', area_key, *(f'{name}={value}' for name, value in sorted(params.items())))
        packed = cache.get(key)
        if packed is None:
            packed = zlib.compress(self.payload(shape, filters).encode(), 6)
            try:
                cache.set(key, packed, self.cache_timeout)
            except Exception as err:
                logger.warning('Could not cache %s: %s', key, err)
        return HttpResponse(zlib.decompress(packed), content_type='application/json')

    @staticmethod
    def payload(shape=None, filters=None):
        index = {status: i for i, status in enumerate(STATUSES)}
        queryset = Well.objects.only('id', 'status', 'in_hpz', 'point').order_by('pk')
        if filters:
            queryset = wells.filter_wells(queryset, **filters)
        if shape is not None:
            queryset = queryset.filter(point__intersects=shape)
        rows = [
            [well.sqid, round(well.point.x, 5), round(well.point.y, 5), index.get(well.status, 0), 1 if well.in_hpz == Well.HPZ.VERIFIED else 0]
            for well in queryset.iterator(chunk_size=5000)
        ]
        stamp = wells.stamp()
        return json.dumps({
            'imported': stamp.imported_at.date().isoformat() if stamp else None,
            'statuses': STATUSES,
            'wells': rows,
        }, separators=(',', ':'))


class WellAreas(generics.Endpoint):
    """
    Wells per area for the Oil & gas map's Areas view: ?level= (county,
    zipcode, tract; required) and the table's filters (status, hpz, q,
    operator, field). `{"level", "unit": "wells", "areas": [{id, wells,
    active, hpz, per_sq_mi, hpz_share}]}`, only areas with a well; shapes
    come from /api/2.0/regions/geojson/?type=<level>&simplify=1, joined on
    `id`. Counts of CalGEM records, not emissions.
    """

    def get(self, request):
        from camp.apps.emissions import areas
        level = request.GET.get('level', '')
        if level not in areas.LEVELS:
            return HttpResponse(json.dumps({'error': f"level must be one of {', '.join(areas.LEVELS)}."}), status=400, content_type='application/json')
        filters = {name: value for name, value in wells.table_filters(request.GET).items() if name != 'sort'}
        return wells.area_values(level, filters)


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
            'map_url': well.well_finder_url,
        }
