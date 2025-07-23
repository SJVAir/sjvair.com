from resticus.filters import FilterSet

from camp.apps.integrate.tempo.models import O3totFile, HchoFile, No2File


class O3totFilter(FilterSet):
    model = O3totFile
    fields = {
        'timestamp': [
            'exact', 
            'lt', 'lte',
            'gt', 'gte',
        ]
    }
    
    
class HchoFilter(FilterSet):
    model = HchoFile
    fields = {
        'timestamp': [
            'exact', 
            'lt', 'lte',
            'gt', 'gte',
        ]
    }
    
    
class No2Filter(FilterSet):
    model = No2File
    fields = {
        'timestamp': [
            'exact', 
            'lt', 'lte',
            'gt', 'gte',
        ]
    }
    