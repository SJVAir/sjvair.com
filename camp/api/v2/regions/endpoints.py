from resticus import generics

from camp.apps.regions.models import Region

from .filters import RegionFilter
from .serializers import RegionDetailSerializer, RegionSerializer


class RegionMixin:
    model = Region
    serializer_class = RegionSerializer

    def get_queryset(self):
        return super().get_queryset().select_related('boundary')


class RegionList(RegionMixin, generics.ListEndpoint):
    filter_class = RegionFilter
    paginate = False


class RegionDetail(RegionMixin, generics.DetailEndpoint):
    serializer_class = RegionDetailSerializer
    lookup_field = 'pk'
    lookup_url_kwarg = 'region_id'
