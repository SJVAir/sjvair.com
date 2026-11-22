import django_filters

from resticus.filters import FilterSet

from camp.apps.monitors.models import Monitor
from camp.apps.regions.models import Region
from camp.apps.summaries.models import MonitorSummary, RegionSummary


class BulkMonitorScopeFilter(FilterSet):
    # Declared only so these show up in the generated OpenAPI schema; the
    # actual filtering happens in BulkMonitorScopeMixin (bbox and type via
    # BulkMonitorScopeForm, region via request.GET.getlist(), processor via
    # get_processor_filter()), same idiom as CES4Filter.year.
    type = django_filters.CharFilter(
        method='noop',
        help_text=(
            'Monitor type id (as in monitors/meta/); repeatable. Only these types are '
            'returned; the only way to reach an opt-in type (cimis), served raw.'
        ),
    )
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


class BulkMonitorSummaryFilter(BulkMonitorScopeFilter):
    start = django_filters.DateFilter(method='noop', help_text='Inclusive start date (required).')
    end = django_filters.DateFilter(method='noop', help_text='Inclusive end date (required).')

    class Meta:
        model = MonitorSummary
        fields = []


class BulkMonitorOpenDaysFilter(BulkMonitorScopeFilter):
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
