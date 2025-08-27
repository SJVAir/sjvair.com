from django.urls import path

from . import endpoints

app_name = 'tempo'

urlpatterns = [
    path('', endpoints.TempoList.as_view(), name='tempo-list'),
    path('<tempo_id>/', endpoints.TempoDetail.as_view(), name='tempo-detail'),
    
]
