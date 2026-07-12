import django_filters
from resticus.filters import FilterSet

from camp.apps.calheatscore.models import CalHeatScore


class ZipCodeInFilter(django_filters.BaseInFilter, django_filters.CharFilter):
    pass


class CalHeatScoreFilter(FilterSet):
    zip_code = django_filters.CharFilter(field_name='region__external_id')
    zip_code__in = ZipCodeInFilter(field_name='region__external_id', lookup_expr='in')

    class Meta:
        model = CalHeatScore
        fields = {
            'date': ['exact', 'gte', 'lte'],
            'score': ['exact', 'gte', 'lte'],
        }
