from django.urls import path

from .endpoints import BulkRegionOpenDays, BulkRegionOpenPeriods, BulkRegionSummaryList

view = BulkRegionSummaryList.as_view()

urlpatterns = [
    path('hourly/', view, {'resolution': 'hour'}, name='region-summary-bulk-hourly'),
    path('daily/open/', BulkRegionOpenDays.as_view(), {'resolution': 'day'}, name='region-summary-bulk-daily-open'),
    path('daily/', view, {'resolution': 'day'}, name='region-summary-bulk-daily'),
    path('monthly/open/', BulkRegionOpenPeriods.as_view(), {'resolution': 'month'}, name='region-summary-bulk-monthly-open'),
    path('monthly/', view, {'resolution': 'month'}, name='region-summary-bulk-monthly'),
    path('quarterly/open/', BulkRegionOpenPeriods.as_view(), {'resolution': 'quarter'}, name='region-summary-bulk-quarterly-open'),
    path('quarterly/', view, {'resolution': 'quarter'}, name='region-summary-bulk-quarterly'),
    path('seasonal/open/', BulkRegionOpenPeriods.as_view(), {'resolution': 'season'}, name='region-summary-bulk-seasonal-open'),
    path('seasonal/', view, {'resolution': 'season'}, name='region-summary-bulk-seasonal'),
    path('yearly/open/', BulkRegionOpenPeriods.as_view(), {'resolution': 'year'}, name='region-summary-bulk-yearly-open'),
    path('yearly/', view, {'resolution': 'year'}, name='region-summary-bulk-yearly'),
]
