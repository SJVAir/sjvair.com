from resticus.filters import FilterSet

from camp.api.v2.filters import CountyFilter
from camp.apps.integrate.hms_smoke.models import Smoke


class SmokeFilter(FilterSet):
    county = CountyFilter(field_name='geometry', lookup_expr='intersects')
    
    class Meta: 
        model = Smoke
        fields = {
            'density': [
                'iexact',
                'exact',
            ],
            'start': [
                'exact',
                'lt', 'lte',
                'gt', 'gte',
            ],
            'end': [
                'exact',
                'lt', 'lte',
                'gt', 'gte',
            ],
            'satellite': [
                'iexact',
                'exact',
            ],
            'date': [
                'exact',
                'lt', 'lte',
                'gt', 'gte',
            ],
        }
        