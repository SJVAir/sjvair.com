from django.urls import include, path

from . import endpoints

app_name = 'regions'

urlpatterns = [
    path('', endpoints.RegionList.as_view(), name='region-list'),
    path('meta/', endpoints.RegionMetaEndpoint.as_view(), name='region-meta'),
    path('places/search/', endpoints.PlaceSearch.as_view(), name='place-search'),
    path('places/lookup/', endpoints.PlaceLookup.as_view(), name='place-lookup'),
    path('<entry_type>/summaries/', include('camp.api.v2.summaries.region_bulk_urls')),
    path('<region_id>/', endpoints.RegionDetail.as_view(), name='region-detail'),
    path('<region_id>/summaries/', include('camp.api.v2.summaries.region_urls')),
]
