from resticus import generics

from camp.apps.integrate.tempo.models import TempoGrid
from .serializer import TempoSerializer
from .filters import TempoFIlter

class TempoMixin:
    model = TempoGrid
    serializer_class = TempoSerializer
    paginate = True  #defaults to page_size = 100
    def get_queryset(self):    
        return (
            super().get_queryset().order_by('-timestamp')
        )
        
class TempoList(TempoMixin, generics.ListEndpoint):
    filter_class = TempoFIlter

class TempoDetail(TempoMixin, generics.DetailEndpoint):
    lookup_field = 'id'
    lookup_url_kwarg = 'tempo_id'
    