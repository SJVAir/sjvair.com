from resticus import generics
import geopandas as gpd
from django.http import JsonResponse
from ....apps.monitors.cal_enviro_screen_4.services.helpers import *
from ....apps.monitors.cal_enviro_screen_4.models import CalEnviro
from .serializers import Cal_Enviro_Screen_4_Serializer


def getCalData(request):
    geo = gpd.read_file('/vagrant/camp/apps/monitors/cal_enviro_screen_4/calEnvShapefiles/CalEnviroScreen_4.0_Results.shp')
    for i in range(len(geo)):
        for col, val in geo.iloc[i].items():
            print(f"{col}: {val}")
            
            
        break
    return  JsonResponse({'status': 'ok'})


class CalEnviroAllData(generics.EndpointList):
    model = CalEnviro
    serializer = Cal_Enviro_Screen_4_Serializer
    
    def get_queryset(self):
        queryset = super(CLASS_NAME, self).get_queryset()
        queryset = queryset # TODO
        return queryset


