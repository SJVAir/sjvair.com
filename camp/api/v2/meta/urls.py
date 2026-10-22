from django.urls import path

from . import endpoints

app_name = 'meta'

urlpatterns = [
    path('datasets/', endpoints.DatasetCatalogEndpoint.as_view(), name='datasets'),
]
