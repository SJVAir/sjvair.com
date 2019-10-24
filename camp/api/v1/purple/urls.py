from django.urls import path

from . import endpoints

app_name = 'api'

urlpatterns = [
    path('', endpoints.PurpleAirList.as_view(), name='device-list'),
    path('<str:purple_air_id>/', endpoints.PurpleAirDetail.as_view(), name='device-detail'),
    path('<str:purple_air_id>/entries/', endpoints.EntryList.as_view(), name='entry-list'),
]
