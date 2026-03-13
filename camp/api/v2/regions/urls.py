from django.urls import path

from . import endpoints

app_name = 'regions'

urlpatterns = [
    path('', endpoints.RegionList.as_view(), name='region-list'),
    path('<region_id>/', endpoints.RegionDetail.as_view(), name='region-detail'),
    # TODO: add once camp.api.v2.summaries is implemented:
    # path('<region_id>/summaries/', include('camp.api.v2.summaries.region_urls')),
]
