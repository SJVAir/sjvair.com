from resticus import generics

from camp.apps.integrate.ces4.models import Ces4
from .filter import Ces4Filter
from .serializers import Ces4_Serializer

class Ces4Mixin:
    model = Ces4
    serializer_class = Ces4_Serializer

class Ces4List(Ces4Mixin, generics.ListEndpoint):
    filter_class = Ces4Filter
    
class Ces4Detail(Ces4Mixin, generics.DetailEndpoint):
    lookup_field = 'OBJECTID'
    lookup_url_kwarg = 'pk'

