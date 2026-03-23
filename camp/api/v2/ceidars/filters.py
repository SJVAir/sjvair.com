import django_filters
from django.db.models import Max, Prefetch
from resticus.filters import FilterSet

from camp.apps.ceidars.models import EmissionsRecord, Facility


class FacilityFilter(FilterSet):
    year = django_filters.NumberFilter(method='filter_year')
    sources = django_filters.CharFilter(method='filter_sources')
    county = django_filters.CharFilter(field_name='county__slug')
    city = django_filters.CharFilter(field_name='city__slug')
    zipcode = django_filters.CharFilter(field_name='zipcode__name')

    def __init__(self, data=None, *args, **kwargs):
        if data is not None:
            data = data.copy()
            if 'year' not in data:
                data['year'] = EmissionsRecord.objects.aggregate(Max('year'))['year__max']
        return super().__init__(data=data, *args, **kwargs)

    def filter_year(self, queryset, name, value):
        return queryset.filter(emissions__year=value).prefetch_related(
            Prefetch('emissions', queryset=EmissionsRecord.objects.filter(year=value))
        )

    def filter_sources(self, queryset, name, value):
        if value == 'major':
            return queryset.major_sources()
        if value == 'minor':
            return queryset.minor_sources()
        return queryset

    class Meta:
        model = Facility
        fields = {}
