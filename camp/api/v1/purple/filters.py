from resticus.filters import FilterSet

from camp.apps.purple.models import PurpleAir, Entry


class PurpleAirFilter(FilterSet):
    class Meta:
        model = PurpleAir
        fields = {
            'purple_id': [
                'exact'
            ],
            'label': [
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
            ]
        }
