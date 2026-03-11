from django.urls import path

from . import endpoints

app_name = 'ces'

urlpatterns = [
    path('4.0/<str:year>/', endpoints.CES4List.as_view(), name='ces4-list'),
    path('4.0/<str:year>/<str:tract>/', endpoints.CES4Detail.as_view(), name='ces4-detail'),
]
