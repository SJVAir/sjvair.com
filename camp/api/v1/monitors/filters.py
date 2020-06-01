from resticus.filters import FilterSet

from camp.apps.monitors.models import Entry, Monitor


class MonitorFilter(FilterSet):
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
            'location': ['exact'],
        }


class EntryFilter(FilterSet):
    class Meta:
        model = Entry
        fields = {
            'timestamp': [
                'exact',
                'lt', 'lte',
                'gt', 'gte',
            ],
            'is_processed': ['exact'],
        }
