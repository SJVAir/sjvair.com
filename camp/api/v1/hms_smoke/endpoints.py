
# Create your views here.
from resticus import generics
from ....apps.monitors.hms_smoke.models import Smoke
from .serializers import SmokeSerializer
from ....apps.monitors.hms_smoke.services.queries import *
from django.http import Http404
from django.shortcuts import get_object_or_404
from smalluuid import SmallUUID
import os
from django.http import JsonResponse

env = os.environ.get
query_hours = int(os.environ.get('query_hours', 3))

class OngoingSmokeView(generics.ListEndpoint):
    model = Smoke
    serializer_class = SmokeSerializer
    
    def get_queryset(self):
        queryset = query_ongoing_smoke(query_hours).order_by('-end')
        return queryset

class OngoingSmokeDensityView(generics.ListEndpoint):
    model = Smoke
    serializer_class = SmokeSerializer
    def get_queryset(self):
        densities = self.request.GET.getlist('density')
        queryset = query_ongoing_density_smoke(query_hours, densities).order_by('-end')
        return queryset
    
    
class LatestObeservableSmokeView(generics.ListEndpoint):
    model = Smoke
    serializer_class = SmokeSerializer
    def get_queryset(self):
            queryset = query_latest_smoke().order_by('-observation_time')
            return queryset

class LatestObeservableSmokeDensityView(generics.ListEndpoint):
    model = Smoke
    serializer_class = SmokeSerializer
    def get_queryset(self):
        densities = self.request.GET.getlist('density')
        queryset = query_latest_smoke_density(densities).order_by('-observation_time')
        return queryset
        

class SelectSmokeView(generics.Endpoint):
    model = Smoke
    serializer_class = SmokeSerializer
    queryset = Smoke.objects.all()

    def get(self, *args, **kwargs):
        try:
            uuid_str = kwargs['pk']
            #Error check the uuid_str in the bar
            SmallUUID(uuid_str)
            strCheck(uuid_str)
            smoke = get_object_or_404(Smoke, pk=uuid_str)
            smoke_serialized = SmokeSerializer(smoke).serialize()
            return JsonResponse({"data": smoke_serialized})
        except Exception as e:
            uuid_str = self.kwargs.get('pk')
            raise Http404(f"There was a problem retrieving smoke data for id = {uuid_str}")
    
class SmokeByTimestamp(generics.ListEndpoint):
    model = Smoke
    serializer_class = SmokeSerializer
    queryset = Smoke.objects.all()
    
    def get_queryset(self):
        queryset = super().get_queryset()
        return queryset.order_by('-observation_time')
    
    


# Will return today's smokes between times indicated by user according to the most recent observation.
class StartEndFilter(generics.ListEndpoint):
    model = Smoke 
    serializer_class = SmokeSerializer
    
    def get_queryset(self):
        start = self.request.GET.get('start')
        strCheck(start)
        end = self.request.GET.get('end')
        strCheck(end)
        queryset = query_timefilter(start, end)
        return queryset.order_by("-end")
        
        
        
    
    