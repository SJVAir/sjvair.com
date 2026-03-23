from resticus import generics

from camp.apps.regions.models import Region

from .serializers import RegionSerializer


class PlaceSearch(generics.Endpoint):
    def get(self, request):
        q = request.GET.get('q', '').strip()
        place = Region.objects.resolve_place(q) if q else None
        return {'data': RegionSerializer(place).serialize() if place else None}
