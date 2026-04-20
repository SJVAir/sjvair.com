from django.urls import path

from .endpoints import RegionSummaryList

view = RegionSummaryList.as_view()

urlpatterns = [
    # hourly
    path('<entry_type>/hourly/<int:year>/', view, {'resolution': 'hour'}, name='region-summary-hourly-year'),
    path('<entry_type>/hourly/<int:year>/<int:month>/', view, {'resolution': 'hour'}, name='region-summary-hourly-month'),
    path('<entry_type>/hourly/<int:year>/<int:month>/<int:day>/', view, {'resolution': 'hour'}, name='region-summary-hourly-day'),

    # daily
    path('<entry_type>/daily/<int:year>/', view, {'resolution': 'day'}, name='region-summary-daily-year'),
    path('<entry_type>/daily/<int:year>/<int:month>/', view, {'resolution': 'day'}, name='region-summary-daily-month'),

    # coarser resolutions
    path('<entry_type>/monthly/<int:year>/', view, {'resolution': 'month'}, name='region-summary-monthly'),
    path('<entry_type>/quarterly/<int:year>/', view, {'resolution': 'quarter'}, name='region-summary-quarterly'),
    path('<entry_type>/seasonal/<int:year>/', view, {'resolution': 'season'}, name='region-summary-seasonal'),
    path('<entry_type>/yearly/', view, {'resolution': 'year'}, name='region-summary-yearly'),
]
