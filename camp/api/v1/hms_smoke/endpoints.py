
# Create your views here.
from resticus import generics
from ....apps.monitors.hms_smoke.models import Smoke
from .serializers import SmokeSerializer
from ....apps.monitors.hms_smoke.services.queries import *
from django.http import Http404
from django.shortcuts import get_object_or_404
from smalluuid import SmallUUID
import os

env = os.environ.get

class OngoingSmokeView(generics.ListEndpoint):
    model = Smoke
    #TODO CREATE SMOKE SERIALIZER
    serializer_class = SmokeSerializer
    
    def get_queryset(self):
        queryset = query_ongoing_smoke(3).order_by('-observation_time')
        return queryset

class OngoingSmokeDensityView(generics.ListEndpoint):
    model = Smoke
    serializer_class = SmokeSerializer
    def get_queryset(self):
        densities = self.request.GET.getlist('density')
        queryset = query_ongoing_density_smoke(3, densities).order_by('-observation_time')
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
            print(uuid_str)
            SmallUUID(uuid_str)
            stringCheck(uuid_str)
            return get_object_or_404(Smoke, id=uuid_str)
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
    