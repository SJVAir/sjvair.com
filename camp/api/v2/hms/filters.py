from resticus.filters import FilterSet

from camp.apps.hms.models import Fire, Smoke


class SmokeFilter(FilterSet):
    class Meta:
        model = Smoke
        fields = {
            'date': ['exact', 'lt', 'lte', 'gt', 'gte'],
            'satellite': ['exact', 'iexact'],
            'density': ['exact', 'iexact'],
            'start': ['exact', 'lt', 'lte', 'gt', 'gte'],
            'end': ['exact', 'lt', 'lte', 'gt', 'gte'],
        }


class FireFilter(FilterSet):
    class Meta:
        model = Fire
        fields = {
            'date': ['exact', 'lt', 'lte', 'gt', 'gte'],
            'satellite': ['exact', 'iexact'],
            'timestamp': ['exact', 'lt', 'lte', 'gt', 'gte'],
            'method': ['exact', 'iexact'],
        }
