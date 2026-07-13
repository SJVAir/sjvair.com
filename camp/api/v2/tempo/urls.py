from django.urls import path

from . import endpoints

app_name = 'tempo'

urlpatterns = [
    path('', endpoints.TempoProducts.as_view(), name='product-list'),
    path('<str:product>/granules/', endpoints.GranuleList.as_view(), name='granule-list'),
]
