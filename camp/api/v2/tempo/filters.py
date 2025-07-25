from resticus.filters import FilterSet

from camp.apps.integrate.tempo.models import TempoGrid


class O3totFilter(FilterSet):
    model = TempoGrid
    fields = {
        'timestamp': [
            'exact', 
            'lt', 'lte',
            'gt', 'gte',
        ]
    }
    
    
class HchoFilter(FilterSet):
    model = TempoGrid
    fields = {
        'timestamp': [
            'exact', 
            'lt', 'lte',
            'gt', 'gte',
        ]
    }
    
    
class No2Filter(FilterSet):
    model = TempoGrid
    fields = {
        'timestamp': [
            'exact', 
            'lt', 'lte',
            'gt', 'gte',
        ]
    }
    