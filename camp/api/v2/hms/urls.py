from django.urls import path

from . import endpoints

app_name = 'hms'

urlpatterns = [
    path('smoke/', endpoints.SmokeList.as_view(), name='smoke-list'),
    path('smoke/<smoke_id>/', endpoints.SmokeDetail.as_view(), name='smoke-detail'),
    path('fire/', endpoints.FireList.as_view(), name='fire-list'),
    path('fire/<fire_id>/', endpoints.FireDetail.as_view(), name='fire-detail'),
]
