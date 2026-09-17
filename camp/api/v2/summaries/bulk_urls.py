from django.urls import path

from .endpoints import BulkMonitorSummaryList

view = BulkMonitorSummaryList.as_view()

urlpatterns = [
    path('<entry_type>/hourly/', view, {'resolution': 'hour'}, name='monitor-summary-bulk-hourly'),
    path('<entry_type>/daily/', view, {'resolution': 'day'}, name='monitor-summary-bulk-daily'),
    path('<entry_type>/monthly/', view, {'resolution': 'month'}, name='monitor-summary-bulk-monthly'),
    path('<entry_type>/quarterly/', view, {'resolution': 'quarter'}, name='monitor-summary-bulk-quarterly'),
    path('<entry_type>/seasonal/', view, {'resolution': 'season'}, name='monitor-summary-bulk-seasonal'),
    path('<entry_type>/yearly/', view, {'resolution': 'year'}, name='monitor-summary-bulk-yearly'),
]
