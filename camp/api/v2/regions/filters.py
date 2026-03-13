from django_filters import CharFilter
from resticus.filters import FilterSet

from camp.apps.regions.models import Region


class RegionFilter(FilterSet):
    type = CharFilter(field_name='type', lookup_expr='exact')

    class Meta:
        model = Region
        fields = {'type': ['exact']}
