from django.urls import path

from . import endpoints

app_name = 'archive'

urlpatterns = [
    path('', endpoints.ArchiveList.as_view(), name='archive-list'),
    path('<int:year>/<int:month>/', endpoints.ArchiveCSV.as_view(), name='archive-csv'),
]
