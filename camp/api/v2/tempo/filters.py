from resticus.filters import FilterSet

from camp.apps.integrate.tempo.models import TempoGrid


class TempoFIlter(FilterSet):
    model = TempoGrid
    fields = {
        'pollutant': ['exact'],
        
        'timestamp': [
            'exact', 
            'lt', 'lte',
            'gt', 'gte',
        ],
        'timestamp_2': [
            'exact', 
            'lt', 'lte',
            'gt', 'gte',
        ]
    }
    