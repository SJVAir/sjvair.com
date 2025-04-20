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
            calibration = self.data.get('calibration')
            stage = self.data.get('stage')
            sensor = self.form.cleaned_data.get('sensor')

            # Sensor fallback
            if not sensor and self.monitor is not None:
                default_sensor = self.monitor.get_default_sensor(self._meta.model)
                if default_sensor:
                    queryset = queryset.filter(sensor=default_sensor)

            # If calibration is provided explicitly, force stage=calibrated
            if calibration:
                queryset = queryset.filter(
                    stage=EntryModel.Stage.CALIBRATED,
                    calibration=calibration
                )

            # If stage=calibrated is set, but no calibration, use default calibration
            elif stage == EntryModel.Stage.CALIBRATED and EntryModel.is_calibratable:
                calibration = self.monitor.get_default_calibration(EntryModel)
                queryset = queryset.filter(stage=stage, calibration=calibration)

            # If neither stage nor calibration are specified, apply default stage only
            elif not stage and self.monitor is not None:
                stage = self.monitor.get_default_stage(EntryModel)
                queryset = queryset.filter(stage=stage)

            return super().filter_queryset(queryset)

    return EntryFilterSet