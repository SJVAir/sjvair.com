from resticus.filters import FilterSet

from camp.apps.integrate.tempo.models import O3TOT_Points, HCHO_Points, NO2_Points


class O3totFilter(FilterSet):
    model = O3TOT_Points
    fields = {
        'timestamp': [
            'exact', 
            'lt', 'lte',
            'gt', 'gte',
        ]
    }
    
    
class HchoFilter(FilterSet):
    model = HCHO_Points
    fields = {
        'timestamp': [
            'exact', 
            'lt', 'lte',
            'gt', 'gte',
        ]
    }
    
    
class No2Filter(FilterSet):
    model = NO2_Points
    fields = {
        'timestamp': [
            'exact', 
            'lt', 'lte',
            'gt', 'gte',
        ]
    }
    