from resticus import generics

from camp.apps.integrate.ces4.models import Ces4
from .serializers import Ces4_Serializer
from .filter import Ces4Filter

class ces4Mixin:
    model = Ces4
    serializer_class = Ces4_Serializer

class Ces4List(ces4Mixin, generics.ListEndpoint):
    filter = Ces4Filter
    
class Ces4Detail(ces4Mixin, generics.DetailEndpoint):
    lookup_field = 'OBJECTID'
    lookup_url_kwarg = 'pk'


