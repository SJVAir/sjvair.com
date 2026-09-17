import django_filters

from resticus.filters import FilterSet

from camp.apps.summaries.models import MonitorSummary


class BulkMonitorSummaryFilter(FilterSet):
    # Declared only so these show up in the generated OpenAPI schema; the
    # actual filtering happens in BulkMonitorSummaryList.get_queryset() /
    # get_date_filter() (start/end/bbox are form fields, region is read via
    # request.GET.getlist(), same as MonitorsAt).
    start = django_filters.DateFilter(method='noop')
    end = django_filters.DateFilter(method='noop')
    bbox = django_filters.CharFilter(method='noop')
    region = django_filters.CharFilter(method='noop')

    def noop(self, queryset, name, value):
        return queryset

    class Meta:
        model = MonitorSummary
        fields = []
