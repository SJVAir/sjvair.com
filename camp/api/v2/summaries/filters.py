import django_filters

from resticus.filters import FilterSet

from camp.apps.summaries.models import MonitorSummary


class BulkMonitorSummaryFilter(FilterSet):
    # Declared only so these show up in the generated OpenAPI schema; the
    # actual filtering happens in BulkMonitorSummaryList (start/end/bbox via
    # BulkMonitorSummaryForm, region via request.GET.getlist(), processor via
    # get_processor_filter()), same idiom as CES4Filter.year.
    start = django_filters.DateFilter(method='noop', help_text='Inclusive start date (required).')
    end = django_filters.DateFilter(method='noop', help_text='Inclusive end date (required).')
    bbox = django_filters.CharFilter(method='noop', help_text='west,south,east,north')
    region = django_filters.CharFilter(method='noop', help_text='Region id; repeatable.')
    processor = django_filters.CharFilter(
        method='noop',
        help_text=(
            'Exact summary processor to return (blank for raw). When omitted, '
            "each monitor's published series is used."
        ),
    )

    def noop(self, queryset, name, value):
        return queryset

    class Meta:
        model = MonitorSummary
        fields = []
