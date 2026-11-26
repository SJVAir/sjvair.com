from django.urls import path

from . import endpoints

app_name = 'forecasts'

urlpatterns = [
    path('', endpoints.ForecastList.as_view(), name='forecast-list'),
    path('meta/', endpoints.ForecastMeta.as_view(), name='forecast-meta'),
    path('place/', endpoints.ForecastPlace.as_view(), name='forecast-place'),
    path('<forecast_id>/', endpoints.ForecastDetail.as_view(), name='forecast-detail'),
]
