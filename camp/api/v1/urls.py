from django.urls import include, path

from . import endpoints

app_name = 'api'

urlpatterns = [
    path('time/', endpoints.CurrentTime.as_view(), name='current-time'),
    path('sensors/', include('camp.api.v1.sensors.urls', namespace='sensors')),
    path('purple-air/', include('camp.api.v1.purple.urls', namespace='purple-air')),
]
