from django.urls import path

from . import endpoints

app_name = 'regions'

urlpatterns = [
    path('places/search/', endpoints.PlaceSearch.as_view(), name='place-search'),
]
