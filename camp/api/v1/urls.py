from django.urls import include, path

app_name = 'api'

urlpatterns = [
    path('sensors/', include('camp.api.v1.sensors.urls', namespace='sensors')),
]
