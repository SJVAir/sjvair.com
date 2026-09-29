"""
The methane layer for our own maps. Deliberately not under /api/2.0/ and not
in the API docs: Carbon Mapper's terms are non-commercial with share-alike
redistribution, and until Carbon Mapper confirms a public endpoint in writing
the data is served only to this site's pages (spec, open question 1). The
body still carries the licence and attribution, as the terms require.
"""
from django.http import Http404, JsonResponse
import vanilla

from camp.apps.emissions import methane


class MethaneGeoJSON(vanilla.View):
    def get(self, request):
        if not methane.enabled():
            raise Http404('No methane sources imported.')
        response = JsonResponse(methane.collection())
        response['Cache-Control'] = 'private, max-age=3600'
        response['X-Robots-Tag'] = 'noindex'
        return response
