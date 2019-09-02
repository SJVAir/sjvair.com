from resticus.filters import FilterSet

from camp.apps.sensors.models import Sensor, SensorData


class SensorFilter(FilterSet):
    class Meta:
        model = Sensor
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


class SensorDataFilter(FilterSet):
    class Meta:
        model = SensorData
        fields = {
            'timestamp': [
                'exact',
                'lt', 'lte',
                'gt', 'gte',
            ]
        }
