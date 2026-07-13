from django.urls import path

from . import endpoints

app_name = 'tempo'

urlpatterns = [
    path('', endpoints.TempoProducts.as_view(), name='product-list'),
]
