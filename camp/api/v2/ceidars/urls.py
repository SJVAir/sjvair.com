from django.urls import path

from . import endpoints

app_name = 'ceidars'

urlpatterns = [
    path('', endpoints.FacilityList.as_view(), name='list'),
    path('<str:sqid>/', endpoints.FacilityDetail.as_view(), name='detail'),
]
