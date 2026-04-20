from resticus import generics

from camp.apps.regions.models import Region

from .filters import RegionFilter
from .serializers import RegionSerializer


class RegionMixin:
    model = Region
    serializer_class = RegionSerializer

    def get_queryset(self):
        return super().get_queryset().select_related('boundary')


class RegionList(RegionMixin, generics.ListEndpoint):
    filter_class = RegionFilter
    paginate = False


class RegionDetail(RegionMixin, generics.DetailEndpoint):
    lookup_field = 'pk'
    lookup_url_kwarg = 'region_id'


class PlaceSearch(generics.Endpoint):
    """Search for a place by name and return its geographic region data."""

    def get(self, request):
        q = request.GET.get('q', '').strip()
        place = Region.objects.resolve_place(q) if q else None
        return {'data': RegionSerializer(place).serialize() if place else None}
