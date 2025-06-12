from django.urls import path

from . import endpoints

app_name = "hms_smoke"

urlpatterns = [
    path('', endpoints.SmokeList.as_view(), name='smoke-list'),
    path('ongoing/', endpoints.SmokeListOngoing.as_view(), name='smoke-ongoing'),
    path('<smoke_id>/', endpoints.SmokeDetail.as_view(), name='smoke-detail'),
]
