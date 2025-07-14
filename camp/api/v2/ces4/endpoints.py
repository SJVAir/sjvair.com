from resticus import generics

from camp.apps.integrate.ces4.models import Tract
from .filter import Ces4Filter
from .serializers import Ces4_Serializer


class Ces4Mixin:
    model = Tract
    serializer_class = Ces4_Serializer


class Ces4List(Ces4Mixin, generics.ListEndpoint):
    filter_class = Ces4Filter
    paginate = False
    
    
class Ces4Detail(Ces4Mixin, generics.DetailEndpoint):
    lookup_field = 'objectid'
    lookup_url_kwarg = 'pk'
