from django.urls import path

from .endpoints import BulkMonitorSummaryList

view = BulkMonitorSummaryList.as_view()

# Mounted at monitors/<entry_type>/summaries/, alongside closest/, current/, at/.
urlpatterns = [
    path('hourly/', view, {'resolution': 'hour'}, name='monitor-summary-bulk-hourly'),
    path('daily/', view, {'resolution': 'day'}, name='monitor-summary-bulk-daily'),
    path('monthly/', view, {'resolution': 'month'}, name='monitor-summary-bulk-monthly'),
    path('quarterly/', view, {'resolution': 'quarter'}, name='monitor-summary-bulk-quarterly'),
    path('seasonal/', view, {'resolution': 'season'}, name='monitor-summary-bulk-seasonal'),
    path('yearly/', view, {'resolution': 'year'}, name='monitor-summary-bulk-yearly'),
]
