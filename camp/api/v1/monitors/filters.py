import django_filters
from resticus.filters import FilterSet

from camp.apps.monitors.models import Entry, Monitor


class MonitorFilter(FilterSet):
    device = django_filters.CharFilter(method='filter_device')

    def filter_device(self, queryset, name, value):
        lookup_field = {
            'PurpleAir': 'purpleair',
            'AirNow': 'airnow',
            'BAM1022': 'bam1022',
        }.get(value)

        if lookup_field is not None:
            queryset = queryset.filter(**{
                f'{lookup_field}__isnull': False
            })
        return queryset

    class Meta:
        model = Monitor
        fields = {
            'name': [
                'exact',
                'contains',
                'icontains'
            ],
            'position': [
                'exact',
                'bbcontains',
                'bboverlaps',
                'distance_gt',
                'distance_lt'
            ],
            'is_sjvair': ['exact'],
            'location': ['exact'],
            'county': ['exact'],
            # 'device': ['exact'],
        }


class EntryFilter(FilterSet):
    class Meta:
        model = Entry
        fields = {
            'sensor': ['exact'],
            'timestamp': [
                'exact',
                'lt', 'lte',
                'gt', 'gte',
            ],
            'is_processed': ['exact'],
        }
