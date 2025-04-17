from django.urls import include, path

from . import endpoints

app_name = 'calibrations'

urlpatterns = [
    path('', endpoints.CalibratorList.as_view(), name='calibrator-list'),
]
