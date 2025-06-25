
from resticus import generics

from django.db.models import Max
from django.utils import timezone

from .filters import SmokeFilter
from .serializers import SmokeSerializer
from camp.apps.integrate.hms_smoke.models import Smoke


class SmokeMixin:
    model = Smoke
    serializer_class = SmokeSerializer


class SmokeList(SmokeMixin, generics.ListEndpoint):
    filter_class = SmokeFilter
    paginate = False
    
    
class SmokeListOngoing(SmokeMixin, generics.ListEndpoint):
    filter_class = SmokeFilter
    
    def get_queryset(self):
        #Gets from the latest smoke data + ongoing smokes
        curr_time = timezone.now()
        latest_max = Smoke.objects.aggregate(Max('timestamp'))['timestamp__max'] 
        return (super().getqueryset()
                .filter(start__lte=curr_time, end__gte=curr_time, timestamp=latest_max,)
                .order_by('end')
        )


class SmokeDetail(SmokeMixin, generics.DetailEndpoint):
    lookup_field = 'id'
    lookup_url_kwarg = 'smoke_id'
        