import django_filters
from resticus.filters import FilterSet, filterset_factory

from camp.apps.monitors.models import Monitor
from ..filters import TimezoneDateTimeFilter 


class MonitorFilter(FilterSet):
    device = django_filters.CharFilter(method='filter_device')

    def filter_device(self, queryset, name, value):
        lookup_field = {
            'PurpleAir': 'purpleair',
            'AirNow': 'airnow',
            'AQview': 'aqview',
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


def get_entry_filterset(EntryModel):
    fields = {
        'sensor': ['exact'],
        'timestamp': ['date', 'exact', 'lt', 'lte', 'gt', 'gte'],
    }
    
    if EntryModel.is_calibratable:
        fields['calibration'] = ['exact']

    BaseFilterSet = filterset_factory(EntryModel, fields)

    class EntryFilterSet(BaseFilterSet):
        timezone = TimezoneDateTimeFilter()

        def __init__(self, *args, monitor=None, **kwargs):
            super().__init__(*args, **kwargs)
            self.monitor = monitor

        def filter_queryset(self, queryset):
            # Default sensor fallback
            if 'sensor' not in self.data and self.monitor is not None:
                default_sensor = self.monitor.get_default_sensor(EntryModel)
                if default_sensor:
                    queryset = queryset.filter(sensor=default_sensor)

            # Default calibration fallback
            if EntryModel.is_calibratable and 'calibration' not in self.data:
                calibration = self.monitor.get_default_calibration(EntryModel)
                queryset = queryset.filter(calibration=calibration)

            return super().filter_queryset(queryset)

    return EntryFilterSet