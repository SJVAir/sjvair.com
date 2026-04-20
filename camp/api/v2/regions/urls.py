from django.urls import include, path

from . import endpoints

app_name = 'regions'

urlpatterns = [
    path('', endpoints.RegionList.as_view(), name='region-list'),
    path('places/search/', endpoints.PlaceSearch.as_view(), name='place-search'),
    path('<region_id>/', endpoints.RegionDetail.as_view(), name='region-detail'),
    path('<region_id>/summaries/', include('camp.api.v2.summaries.region_urls')),
]
