from django.urls import include, path

from . import endpoints

app_name = 'monitors'

urlpatterns = [
    path('', endpoints.MonitorList.as_view(), name='monitor-list'),
    path('meta/', endpoints.MonitorMetaEndpoint.as_view(), name='monitor-meta'),
    path('<entry_type>/closest/', endpoints.ClosestMonitor.as_view(), name='monitor-closest'),
    path('<entry_type>/current/', endpoints.CurrentData.as_view(), name='current-data'),

    path('<monitor_id>/', endpoints.MonitorDetail.as_view(), name='monitor-detail'),
    path('<monitor_id>/entries/', endpoints.CreateEntry.as_view(), name='entry-create'),

    # Entry export
    # Deprecated in favor of /csv/ and /json/
    path('<monitor_id>/entries/export/', endpoints.EntryExport.as_view(), name='entry-export'),
    path('<monitor_id>/entries/export/csv/', endpoints.EntryExportCSV.as_view(), name='entry-export-csv'),
    path('<monitor_id>/entries/export/json/', endpoints.EntryExportJSON.as_view(), name='entry-export-json'),

    # Entries by type
    path('<monitor_id>/entries/<entry_type>/', endpoints.EntryList.as_view(), name='entry-list'),
    path('<monitor_id>/entries/<entry_type>/csv/', endpoints.EntryCSV.as_view(), name='entry-csv'),

    path('<monitor_id>/alerts/', include('camp.api.v2.alerts.urls', namespace='alerts')),
    path('<monitor_id>/archive/', include('camp.api.v2.archive.urls', namespace='archive')),
]
