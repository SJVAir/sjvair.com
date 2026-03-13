from django.urls import path

from . import endpoints

app_name = 'regions'

urlpatterns = [
    path('', endpoints.RegionList.as_view(), name='region-list'),
    path('<region_id>/', endpoints.RegionDetail.as_view(), name='region-detail'),
]
