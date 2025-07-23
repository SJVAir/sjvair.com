from django.urls import path

from . import endpoints

app_name = 'tempo'

urlpatterns = [
    path('o3tot/', endpoints.O3totList.as_view(), name='o3tot-list'),
    path('hcho/', endpoints.HchoList.as_view(), name='hcho-list'),
    path('no2/', endpoints.No2List.as_view(), name='no2-list'),
]
