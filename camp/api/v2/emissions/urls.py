from django.urls import path

from . import areas, endpoints, geojson, places

app_name = 'emissions'

urlpatterns = [
    path('', endpoints.FacilityList.as_view(), name='list'),
    path('years/', endpoints.YearList.as_view(), name='years'),
    path('areas/', areas.AreaValues.as_view(), name='areas'),
    path('facilities/geojson/', geojson.FacilityGeoJSON.as_view(), name='geojson'),
    path('places/', places.PlaceSearch.as_view(), name='places'),
    path('districts/', geojson.DistrictList.as_view(), name='districts'),
    path('<str:facility_id>/', endpoints.FacilityDetail.as_view(), name='detail'),
]
