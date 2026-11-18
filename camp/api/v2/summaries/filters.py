import django_filters

from resticus.filters import FilterSet

from camp.apps.monitors.models import Monitor
from camp.apps.regions.models import Region
from camp.apps.summaries.models import MonitorSummary, RegionSummary


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


class BulkMonitorScopeFilter(FilterSet):
    # Documents the bulk open-period endpoints' parameters; its filters are
    # no-ops at runtime (BulkMonitorScopeForm, request.GET.getlist('region')
    # and get_processor_filter() do the scoping).
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
        model = Monitor
        fields = []


class BulkRegionScopeFilter(FilterSet):
    # Schema-only, like BulkMonitorSummaryFilter; BulkRegionScopeForm does the scoping.
    region = django_filters.CharFilter(method='noop', help_text='Region id; repeatable. Exclusive with type.')
    type = django_filters.CharFilter(
        method='noop', help_text='Region type; every current region of it. Exclusive with region.',
    )

    def noop(self, queryset, name, value):
        return queryset


class BulkRegionSummaryFilter(BulkRegionScopeFilter):
    start = django_filters.DateFilter(method='noop', help_text='Inclusive start date (required).')
    end = django_filters.DateFilter(method='noop', help_text='Inclusive end date (required).')

    class Meta:
        model = RegionSummary
        fields = []


class BulkRegionOpenDaysFilter(BulkRegionScopeFilter):
    class Meta:
        model = Region
        fields = []
