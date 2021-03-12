from django.urls import include, path

from . import endpoints
from .monitors.endpoints import MethaneData

app_name = 'api'

urlpatterns = [
    path('time/', endpoints.CurrentTime.as_view(), name='current-time'),
    path('monitors/', include('camp.api.v1.monitors.urls', namespace='monitors')),
    path('methane-data/', MethaneData.as_view(), name='methane-data'),
    path('marker.png', endpoints.MapMarker.as_view(), name='marker'),

    # Deprecated.
    path('sensors/', include('camp.api.v1.sensors.urls', namespace='sensors')),
]
