import json
import logging
import zlib

from django.core.cache import cache
from django.http import Http404, HttpResponse
from resticus import generics

from camp.apps.emissions import wells
from camp.apps.emissions.models import Well

logger = logging.getLogger(__name__)
STATUSES = [Well.Status.ACTIVE.value, Well.Status.IDLE.value, Well.Status.NEW.value]


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
        key = wells.key('geojson')
        packed = cache.get(key)
        if packed is None:
            packed = zlib.compress(self.payload().encode(), 6)
            try:
                cache.set(key, packed, self.cache_timeout)
            except Exception as err:
                logger.warning('Could not cache %s: %s', key, err)
        return HttpResponse(zlib.decompress(packed), content_type='application/json')

    @staticmethod
    def payload():
        index = {status: i for i, status in enumerate(STATUSES)}
        rows = [
            [well.sqid, round(well.point.x, 5), round(well.point.y, 5), index.get(well.status, 0), 1 if well.in_hpz == Well.HPZ.VERIFIED else 0]
            for well in Well.objects.only('id', 'status', 'in_hpz', 'point').order_by('pk').iterator(chunk_size=5000)
        ]
        stamp = wells.stamp()
        return json.dumps({
            'imported': stamp.imported_at.date().isoformat() if stamp else None,
            'statuses': STATUSES,
            'wells': rows,
        }, separators=(',', ':'))


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
