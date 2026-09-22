from django.urls import path

from . import endpoints, geojson

app_name = 'emissions'

urlpatterns = [
    path('', endpoints.FacilityList.as_view(), name='list'),
    path('years/', endpoints.YearList.as_view(), name='years'),
    path('facilities/geojson/', geojson.FacilityGeoJSON.as_view(), name='geojson'),
    path('districts/', geojson.DistrictList.as_view(), name='districts'),
    path('<str:facility_id>/', endpoints.FacilityDetail.as_view(), name='detail'),
]
