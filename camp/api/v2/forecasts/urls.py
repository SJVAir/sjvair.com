from django.urls import path

from . import endpoints

app_name = 'forecasts'

urlpatterns = [
    path('', endpoints.ForecastList.as_view(), name='forecast-list'),
    path('<forecast_id>/', endpoints.ForecastDetail.as_view(), name='forecast-detail'),
]
