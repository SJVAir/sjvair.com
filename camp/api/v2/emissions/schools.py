import json

from django.core.cache import cache
from django.http import HttpResponse
from resticus import generics

from camp.apps.regions.models import Location

TYPES = [Location.Type.PUBLIC_SCHOOL.value, Location.Type.PRIVATE_SCHOOL.value, Location.Type.CHILD_CARE.value]
CACHE_KEY = 'emissions:schools-geojson:v1'


class SchoolGeoJSON(generics.Endpoint):
    """
    Every school and licensed child-care center (regions.Location), for the
    main map's locations layer: `{"types": [...], "labels": [...], "sites":
    [[id, lng, lat, type, name], ...]}`, where `type` indexes `types` (and
    `labels`, their display names). Compact like the wells endpoint; about
    3,000 sites. Cached a day.
    """
    cache_timeout = 60 * 60 * 24

    def get(self, request):
        body = cache.get(CACHE_KEY)
        if body is None:
            body = self.payload()
            cache.set(CACHE_KEY, body, self.cache_timeout)
        return HttpResponse(body, content_type='application/json')

    @staticmethod
    def payload():
        index = {kind: i for i, kind in enumerate(TYPES)}
        rows = [
            [site.sqid, round(site.point.x, 5), round(site.point.y, 5), index[site.type], site.name]
            for site in Location.objects.filter(type__in=TYPES, point__isnull=False).only('id', 'type', 'name', 'point').order_by('pk')
        ]
        return json.dumps({
            'types': TYPES,
            'labels': [str(Location.SHORT_TYPES[kind]) for kind in TYPES],
            'sites': rows,
        }, separators=(',', ':'))
