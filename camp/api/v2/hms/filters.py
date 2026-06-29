import django_filters
from resticus.filters import FilterSet

from camp.apps.hms.models import Fire, Smoke
from camp.apps.regions.models import Region


class SmokeFilter(FilterSet):
    region_id = django_filters.CharFilter(method='filter_region_id')

    def filter_region_id(self, queryset, name, value):
        try:
            region = Region.objects.select_related('boundary').get(sqid=value)
        except Region.DoesNotExist:
            return queryset.none()
        try:
            region_geometry = region.boundary.geometry
        except AttributeError:
            return queryset.none()
        return queryset.filter(geometry__intersects=region_geometry)

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
    region_id = django_filters.CharFilter(method='filter_region_id')

    def filter_region_id(self, queryset, name, value):
        try:
            region = Region.objects.select_related('boundary').get(sqid=value)
        except Region.DoesNotExist:
            return queryset.none()
        try:
            region_geometry = region.boundary.geometry
        except AttributeError:
            return queryset.none()
        return queryset.filter(geometry__intersects=region_geometry)

    class Meta:
        model = Fire
        fields = {
            'date': ['exact', 'lt', 'lte', 'gt', 'gte'],
            'satellite': ['exact', 'iexact'],
            'timestamp': ['exact', 'lt', 'lte', 'gt', 'gte'],
            'method': ['exact', 'iexact'],
        }
