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
        'stage': ['exact'],
        'processor': ['exact']
    }
    BaseFilterSet = filterset_factory(EntryModel, fields)

    class EntryFilterSet(BaseFilterSet):
        timezone = TimezoneDateTimeFilter()

        def __init__(self, *args, monitor=None, **kwargs):
            super().__init__(*args, **kwargs)
            self.monitor = monitor

        def filter_queryset(self, queryset):
            processor = self.data.get('processor')
            stage = self.data.get('stage')

            # If neither stage nor calibration are specified, apply default stage
            if not processor and not stage:
                stage = self.monitor.get_default_stage(EntryModel)
                queryset = queryset.filter(stage=stage)

            # If stage=calibrated is set, but no processor, use default calibration
            elif not processor and stage == EntryModel.Stage.CALIBRATED:
                calibration = self.monitor.get_default_calibration(EntryModel)
                queryset = queryset.filter(stage=stage, processor=calibration)

            return super().filter_queryset(queryset)

    return EntryFilterSet
