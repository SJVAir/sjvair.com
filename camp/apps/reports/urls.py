from django.urls import path

from camp.apps.reports import views  # noqa: F401 -- importing registers the reports
from camp.apps.reports.base import REPORTS, ReportIndex

urlpatterns = [
    path('', ReportIndex.as_view(), name='index'),
    *[path(f'{report.slug}/', report.as_view(), name=report.slug) for report in REPORTS],
]
