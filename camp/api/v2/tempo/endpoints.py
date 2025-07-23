from resticus import generics

from camp.apps.integrate.tempo.models import O3TOT_Points, HCHO_Points, NO2_Points
from .serializer import O3totSerializer, HchoSerializer, No2Serializer
from .filters import O3totFilter, HchoFilter, No2Filter

class O3totMixin:
    model = O3TOT_Points
    serializer_class = O3totSerializer
    paginate = True  #defaults to page_size = 100
    def get_queryset(self):    
        return (
            super().get_queryset().order_by('-timestamp')
        )
    
class HchoMixin:
    model = HCHO_Points
    serializer_class = HchoSerializer
    paginate = True  #defaults to page_size = 100
    def get_queryset(self):    
        return (
            super().get_queryset().order_by('-timestamp')
        )
    
class No2Mixin:
    model = NO2_Points
    serializer_class = No2Serializer
    paginate = True  #defaults to page_size = 100
    def get_queryset(self):    
        return (
            super().get_queryset().order_by('-timestamp')
        )
        
class O3totList(O3totMixin, generics.ListEndpoint): #Maybe not list endpoint because we need to return shapefiles not a queryset
    filter_class = O3totFilter
    
    
class HchoList(HchoMixin, generics.ListEndpoint): #Maybe not list endpoint because we need to return shapefiles not a queryset
    filter_class = HchoFilter


class No2List(No2Mixin, generics.ListEndpoint): #Maybe not list endpoint because we need to return shapefiles not a queryset
    filter_class = No2Filter




