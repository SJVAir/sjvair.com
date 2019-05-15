from django.urls import path

from . import views

app_name = 'sensors'

urlpatterns = [
    path('', views.SensorList.as_view(), name='sensor-list'),
    path('<str:sensor_id>/', views.SensorDetail.as_view(), name='sensor-detail'),
    path('<str:sensor_id>/data/', views.SensorData.as_view(), name='sensor-data'),
]
