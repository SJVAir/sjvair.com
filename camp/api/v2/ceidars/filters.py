import django_filters
from resticus.filters import FilterSet

from camp.apps.ceidars.models import Facility


class FacilityFilter(FilterSet):
    sources = django_filters.CharFilter(method='filter_sources')
    county = django_filters.CharFilter(field_name='county__slug')
    city = django_filters.CharFilter(field_name='city__slug')
    zipcode = django_filters.CharFilter(field_name='zipcode__name')

    def filter_sources(self, queryset, name, value):
        if value == 'major':
            return queryset.major_sources()
        if value == 'minor':
            return queryset.minor_sources()
        return queryset

    class Meta:
        model = Facility
        fields = {}
