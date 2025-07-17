from django.urls import include, path

from . import endpoints
from .alerts.endpoints import SubscriptionList

app_name = 'api'

urlpatterns = [
    path('time/', endpoints.CurrentTime.as_view(), name='current-time'),
    path('alerts/subscriptions/', SubscriptionList.as_view(), name='subscription-list'),

    path('account/', include('camp.api.v1.accounts.urls', namespace='account')),
    path('monitors/', include('camp.api.v1.monitors.urls', namespace='monitors')),
    path('calibrations/', include('camp.api.v1.calibrations.urls', namespace='calibrations')),
    path('marker.png', endpoints.MapMarker.as_view(), name='marker'),

]
