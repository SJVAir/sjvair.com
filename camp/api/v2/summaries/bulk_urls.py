from django.urls import path

from .endpoints import BulkMonitorOpenDays, BulkMonitorOpenPeriods, BulkMonitorSummaryList

view = BulkMonitorSummaryList.as_view()

# Mounted at monitors/<entry_type>/summaries/, alongside closest/, current/, at/.
urlpatterns = [
    path('hourly/', view, {'resolution': 'hour'}, name='monitor-summary-bulk-hourly'),
    path('daily/open/', BulkMonitorOpenDays.as_view(), {'resolution': 'day'}, name='monitor-summary-bulk-daily-open'),
    path('daily/', view, {'resolution': 'day'}, name='monitor-summary-bulk-daily'),
    path('monthly/open/', BulkMonitorOpenPeriods.as_view(), {'resolution': 'month'}, name='monitor-summary-bulk-monthly-open'),
    path('monthly/', view, {'resolution': 'month'}, name='monitor-summary-bulk-monthly'),
    path('quarterly/open/', BulkMonitorOpenPeriods.as_view(), {'resolution': 'quarter'}, name='monitor-summary-bulk-quarterly-open'),
    path('quarterly/', view, {'resolution': 'quarter'}, name='monitor-summary-bulk-quarterly'),
    path('seasonal/open/', BulkMonitorOpenPeriods.as_view(), {'resolution': 'season'}, name='monitor-summary-bulk-seasonal-open'),
    path('seasonal/', view, {'resolution': 'season'}, name='monitor-summary-bulk-seasonal'),
    path('yearly/open/', BulkMonitorOpenPeriods.as_view(), {'resolution': 'year'}, name='monitor-summary-bulk-yearly-open'),
    path('yearly/', view, {'resolution': 'year'}, name='monitor-summary-bulk-yearly'),
]
