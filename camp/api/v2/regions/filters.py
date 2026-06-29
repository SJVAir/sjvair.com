import django_filters
from resticus.filters import FilterSet

from camp.apps.regions.models import Region


class RegionFilter(FilterSet):
    name = django_filters.CharFilter(field_name='name', lookup_expr='icontains')
    slug = django_filters.CharFilter(field_name='slug', lookup_expr='exact')
    type = django_filters.CharFilter(field_name='type', lookup_expr='exact')

    class Meta:
        model = Region
        fields = {}
