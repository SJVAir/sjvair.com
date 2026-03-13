import django_filters
from resticus.filters import FilterSet

from camp.apps.regions.models import Region


class RegionFilter(FilterSet):
    type = django_filters.CharFilter(field_name='type', lookup_expr='exact')

    class Meta:
        model = Region
        fields = ['type']
