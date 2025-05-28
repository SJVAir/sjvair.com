
# Create your views here.
from resticus import generics
from ....apps.monitors.hms_smoke.models import Smoke
import environ 
from .serializers import SmokeSerializer
from ....apps.monitors.hms_smoke.services.queries import *
from django.http import Http404
from django.shortcuts import get_object_or_404
from smalluuid import SmallUUID

env = environ.Env()
environ.Env.read_env() 
class OngoingSmokeView(generics.ListEndpoint):
    model = Smoke
    #TODO CREATE SMOKE SERIALIZER
    serializer_class = SmokeSerializer
    
    def get_queryset(self):
        queryset = query_ongoing_smoke(env('query_hours'))
        return queryset

class OngoingSmokeDensityView(generics.ListEndpoint):
    model = Smoke
    serializer_class = SmokeSerializer
    def get_queryset(self):
        #get densities from query in url
        densities = self.request.query_params.getlist('density')
        queryset = query_ongoing_density_smoke(env('query_hours'), densities)
        return queryset
    
    
class LatestObeservableSmokeView(generics.ListEndpoint):
    model = Smoke
    serializer_class = SmokeSerializer
    def get_queryset(self):
            queryset = query_latest_smoke()
            return queryset

class LatestObeservableSmokeDensityView(generics.ListEndpoint):
    model = Smoke
    serializer_class = SmokeSerializer
    def get_queryset(self):
        densities = self.request.query_params.getlist('density')
        queryset = query_latest_smoke_density(densities)
        return queryset
        

class SelectSmokeView(generics.Endpoint):
    model = Smoke
    serializer_class = SmokeSerializer
    queryset = Smoke.objects.all()

    def get_object(self):
        try:
            #get pk from query
            uuid_str = self.kwargs.get(self.lookup_field)
            SmallUUID(uuid_str)
            stringCheck(uuid_str)
            return get_object_or_404(Smoke, id=uuid_str)
        except Exception as e:
            uuid_str = self.kwargs.get(self.lookup_field)
            raise Http404(f"There was a problem retrieving smoke data for id = {uuid_str}")
    