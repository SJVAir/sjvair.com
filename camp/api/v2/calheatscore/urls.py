from django.urls import path

from . import endpoints

app_name = 'calheatscore'

urlpatterns = [
    path('', endpoints.CalHeatScoreList.as_view(), name='calheatscore-list'),
    path('meta/', endpoints.CalHeatScoreMeta.as_view(), name='calheatscore-meta'),
    path('<str:zipcode>/', endpoints.CalHeatScoreByZip.as_view(), name='calheatscore-by-zip'),
]
