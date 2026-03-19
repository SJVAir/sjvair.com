from django.urls import path

from . import endpoints

app_name = 'ceidars'

urlpatterns = [
    path('', endpoints.CeidarsEndpoint.as_view(), name='list'),
    path('<int:year>/', endpoints.CeidarsEndpoint.as_view(), name='list-by-year'),
]
