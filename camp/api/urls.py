from django.urls import include, path
from django.views import generic

from resticus.views import OpenAPISchemaView

from .v1 import urls as urls_v1_0

app_name = 'api'

urlpatterns = [
    path('2.0/', include('camp.api.v2.urls', namespace='v2')),

    path('1.0/', include('camp.api.v1.urls', namespace='v1')),
    path('1.0/schema/', OpenAPISchemaView.as_view(
        title='SJVAir API v1.0', urlconf=urls_v1_0,
    ), name="schema_v1_0"),
    path('1.0/swagger/',
        generic.TemplateView.as_view(
            template_name="swagger/index.html",
            extra_context={"schema_url": "api:schema_v1_0"},
        ),
        name="swagger",
    ),
]
