from django.urls import path

from .endpoints import MonitorSummaryList

view = MonitorSummaryList.as_view()

urlpatterns = [
    # hourly
    path('<entry_type>/hourly/<int:year>/', view, {'resolution': 'hour'}, name='monitor-summary-hourly-year'),
    path('<entry_type>/hourly/<int:year>/<int:month>/', view, {'resolution': 'hour'}, name='monitor-summary-hourly-month'),
    path('<entry_type>/hourly/<int:year>/<int:month>/<int:day>/', view, {'resolution': 'hour'}, name='monitor-summary-hourly-day'),

    # daily
    path('<entry_type>/daily/<int:year>/', view, {'resolution': 'day'}, name='monitor-summary-daily-year'),
    path('<entry_type>/daily/<int:year>/<int:month>/', view, {'resolution': 'day'}, name='monitor-summary-daily-month'),

    # coarser resolutions
    path('<entry_type>/monthly/<int:year>/', view, {'resolution': 'month'}, name='monitor-summary-monthly'),
    path('<entry_type>/quarterly/<int:year>/', view, {'resolution': 'quarter'}, name='monitor-summary-quarterly'),
    path('<entry_type>/seasonal/<int:year>/', view, {'resolution': 'season'}, name='monitor-summary-seasonal'),
    path('<entry_type>/yearly/', view, {'resolution': 'year'}, name='monitor-summary-yearly'),
]
