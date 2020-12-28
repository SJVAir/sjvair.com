from django.urls import include, path

from . import endpoints

app_name = 'bam1022'

urlpatterns = [
    path('<monitor_id>/entries/', endpoints.EntryList.as_view(), name='entry-list'),
]
