from django.urls import include, path

from resticus.views import DocsView, OpenAPISchemaView

from . import endpoints
from .alerts.endpoints import SubscriptionList

app_name = 'api'

urlpatterns = [
    path('openapi.json', OpenAPISchemaView.as_view(
        title='SJVAir API',
        version='2.0',
        description='Air quality monitoring data for the San Joaquin Valley.',
        urlconf='camp.api.v2.urls',
    ), name='openapi-schema'),

    path('docs/', DocsView.as_view(
        ui='scalar',
        schema_url='/api/2.0/openapi.json',
        title='SJVAir API Docs',
    ), name='api-docs'),

    path('time/', endpoints.CurrentTime.as_view(), name='current-time'),
    path('alerts/subscriptions/', SubscriptionList.as_view(), name='subscription-list'),

    path('account/', include('camp.api.v2.accounts.urls', namespace='account')),
    path('monitors/', include('camp.api.v2.monitors.urls', namespace='monitors')),
    path('calibrations/', include('camp.api.v2.calibrations.urls', namespace='calibrations')),
    path('calenviroscreen/', include('camp.api.v2.ces.urls', namespace='ces')),
    path('hms-smoke/', include('camp.api.v2.hms_smoke.urls', namespace='hms-smoke')),
    path('regions/', include('camp.api.v2.regions.urls', namespace='regions')),
    path('ceidars/', include('camp.api.v2.ceidars.urls', namespace='ceidars')),
    path('hms/', include('camp.api.v2.hms.urls', namespace='hms')),
    path('task/<task_id>/', endpoints.TaskStatus.as_view(), name='task-status'),
]
