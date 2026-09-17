from django.urls import path

from .endpoints import BulkRegionSummaryList

view = BulkRegionSummaryList.as_view()

urlpatterns = [
    path('hourly/', view, {'resolution': 'hour'}, name='region-summary-bulk-hourly'),
    path('daily/', view, {'resolution': 'day'}, name='region-summary-bulk-daily'),
    path('monthly/', view, {'resolution': 'month'}, name='region-summary-bulk-monthly'),
    path('quarterly/', view, {'resolution': 'quarter'}, name='region-summary-bulk-quarterly'),
    path('seasonal/', view, {'resolution': 'season'}, name='region-summary-bulk-seasonal'),
    path('yearly/', view, {'resolution': 'year'}, name='region-summary-bulk-yearly'),
]
