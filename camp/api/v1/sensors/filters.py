from resticus.filters import FilterSet

from camp.apps.sensors.models import Sensor


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
