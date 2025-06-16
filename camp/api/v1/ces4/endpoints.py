from resticus import generics
import geopandas as gpd
from django.http import JsonResponse
from camp.apps.integrate.ces4.models import Ces4
from .serializers import Ces4_Serializer
from django.shortcuts import get_object_or_404
from django.http import JsonResponse
from .filter import Ces4Filter

class ces4Mixin:
    model = Ces4
    serializer_class = Ces4_Serializer

class Ces4List(ces4Mixin, generics.ListEndpoint):
    filter = Ces4Filter
    
class Ces4Detail(ces4Mixin, generics.DetailEndpoint):
    lookup_field = 'OBJECTID'
    lookup_url_kwarg = 'pk'



# def getCalData(request):
#     geo = gpd.read_file('/camp/apps/integrate/ces4/calEnvShapefiles/CalEnviroScreen_4.0_Results.shp')
#     for i in range(len(geo)):
#         for col, val in geo.iloc[i].items():
#             print(f"{col}: {val}") 
#         break
#     return  JsonResponse({'status': 'ok'})


# class CalEnviroDataByTract(generics.ListEndpoint):
#     model = CalEnviro
#     serializer = Cal_Enviro_Screen_4_ALL_Serializer
    
#     def get_queryset(self, *args, **kwargs):
        
#         tract = kwargs['pk']
#         data = get_object_or_404(CalEnviro, tract=tract)
#         data_serialized = Cal_Enviro_Screen_4_ALL_Serializer(data).serialize()
#         return JsonResponse({"data": data_serialized})


