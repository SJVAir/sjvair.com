
# Create your views here.
from resticus import generics
from ....apps.integrate.hms_smoke.models import Smoke
from .serializers import SmokeSerializer
from ....apps.integrate.hms_smoke.services.queries import *
from django.http import Http404
from django.shortcuts import get_object_or_404
from smalluuid import SmallUUID
import os
from django.http import JsonResponse
from ....apps.integrate.hms_smoke.services.helpers import *

env = os.environ.get
query_hours = int(os.environ.get('query_hours', 3))

class OngoingSmokeView(generics.ListEndpoint):
    model = Smoke
    serializer_class = SmokeSerializer
    
    def get_queryset(self):
        queryset = ongoing(query_hours).order_by('-end')
        return queryset

class OngoingSmokeDensityView(generics.ListEndpoint):
    model = Smoke
    serializer_class = SmokeSerializer
    
    def get_queryset(self):
        densities = self.request.GET.getlist('density')
        queryset = ongoing_density(query_hours, densities).order_by('-end')
        return queryset
    
    
class LatestObeservableSmokeView(generics.ListEndpoint):
    model = Smoke
    serializer_class = SmokeSerializer
    
    def get_queryset(self):
            queryset = latest().order_by('-observation_time')
            return queryset


class LatestObeservableSmokeDensityView(generics.ListEndpoint):
    model = Smoke
    serializer_class = SmokeSerializer
    
    def get_queryset(self):
        densities = self.request.GET.getlist('density')
        queryset = latest_density(densities).order_by('-observation_time')
        return queryset
        

class SelectSmokeView(generics.Endpoint):
    model = Smoke
    serializer_class = SmokeSerializer
    queryset = Smoke.objects.all()

    def get(self, *args, **kwargs):
        try:
            uuid_str = kwargs['pk']
            SmallUUID(strCheck(uuid_str))
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
        end = self.request.GET.get('end')

        dt = currentTime()
        year = dt.year
        day = dt.timetuple().tm_yday
        
        start = str(year) + str(day) + " " + start
        end = str(year) + str(day) + " " + end
        
        cleaned = totalHelper(
            Start = start,
            End = end,
        )
        queryset = timefilter(cleaned["Start"], cleaned["End"])
        return queryset.order_by("-end")
        
        
        
    
    