
from resticus import generics
from datetime import timedelta

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
    
    
class SmokeListOngoing(SmokeMixin, generics.ListEndpoint):
    filter_class = SmokeFilter
    
    def get_queryset(self):
        #Gets from the latest smoke data + ongoing smokes
        queryset = super().get_queryset()
        curr_time = timezone.now()
        latest_max = Smoke.objects.aggregate(Max('created'))['created__max'] 
        latest_range = latest_max - timedelta(minutes=1)    #latest smoke data added within a minute of the last data entry
        queryset = queryset.filter(
            start__lte=curr_time,
            end__gte=curr_time,
            created__lte=latest_max,
            created__gte=latest_range
            )
        return queryset


class SmokeDetail(SmokeMixin, generics.DetailEndpoint):
    lookup_field = 'id'
    lookup_url_kwarg = 'smoke_id'
        
    
    