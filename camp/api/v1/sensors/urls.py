from django.urls import path

from . import endpoints

app_name = 'api'

urlpatterns = [
    path('', endpoints.SensorList.as_view(), name='sensor-list'),
    path('<str:sensor_id>/', endpoints.SensorDetail.as_view(), name='sensor-detail'),
    path('<str:sensor_id>/data/', endpoints.SensorData.as_view(), name='sensor-data'),
    path('<str:sensor_id>/export/', endpoints.DataExport.as_view(), name='data-export'),
]
