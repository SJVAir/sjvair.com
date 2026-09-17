import django_filters
from resticus.filters import FilterSet

from camp.apps.regions.models import Region


class RegionFilter(FilterSet):
    name = django_filters.CharFilter(field_name='name', lookup_expr='icontains')
    slug = django_filters.CharFilter(field_name='slug', lookup_expr='exact')
    type = django_filters.CharFilter(field_name='type', lookup_expr='exact')
    # Declared only so this shows up in the generated OpenAPI schema; the
    # actual filtering happens in RegionList.get_queryset() since it needs
    # to union multiple `within` values' geometries before filtering,
    # which a single-field django_filters method can't express cleanly.
    within = django_filters.CharFilter(method='noop', help_text='Parent region id; repeatable.')

    def noop(self, queryset, name, value):
        return queryset

    class Meta:
        model = Region
        fields = {}
