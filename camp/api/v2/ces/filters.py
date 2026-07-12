import django_filters
from resticus.filters import FilterSet

from camp.apps.ces.models import CES4
from camp.apps.regions.models import Region


class CES4Filter(FilterSet):
    year = django_filters.CharFilter(field_name='boundary__version')
    region_id = django_filters.CharFilter(method='filter_region_id')

    def filter_region_id(self, queryset, name, value):
        try:
            region = Region.objects.select_related('boundary').get(sqid=value)
        except Region.DoesNotExist:
            return queryset.none()
        try:
            geometry = region.boundary.geometry
        except AttributeError:
            return queryset.none()
        return queryset.filter(boundary__geometry__intersects=geometry)

    class Meta:
        model = CES4
        fields = {
            'dac_sb535': ['exact'],
            'dac_category': ['exact'],
            'ci_score': ['exact', 'lt', 'lte', 'gt', 'gte'],
            'ci_score_p': ['exact', 'lt', 'lte', 'gt', 'gte'],
            'pollution_p': ['exact', 'lt', 'lte', 'gt', 'gte'],
            'popchar_p': ['exact', 'lt', 'lte', 'gt', 'gte'],
            'pol_pm_p': ['exact', 'lt', 'lte', 'gt', 'gte'],
            'pol_ozone_p': ['exact', 'lt', 'lte', 'gt', 'gte'],
            'pol_diesel_p': ['exact', 'lt', 'lte', 'gt', 'gte'],
            'pol_traffic_p': ['exact', 'lt', 'lte', 'gt', 'gte'],
        }
