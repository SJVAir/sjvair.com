import django_filters
from django.db.models import Max, Prefetch
from resticus.filters import FilterSet

from camp.apps.emissions.models import EmissionsRecord, Facility


class FacilityFilter(FilterSet):
    # A CharFilter (not NumberFilter) so an invalid value reaches filter_year
    # instead of being silently dropped by form validation -- an invalid
    # year should return no results, not the unfiltered queryset.
    year = django_filters.CharFilter(method='filter_year')
    sources = django_filters.CharFilter(method='filter_sources')
    county = django_filters.CharFilter(field_name='county__slug')
    city = django_filters.CharFilter(field_name='city__slug')
    zipcode = django_filters.CharFilter(field_name='zipcode__name')

    def __init__(self, data=None, *args, **kwargs):
        if data is not None:
            data = data.copy()
            if not data.get('year'):
                data['year'] = EmissionsRecord.objects.aggregate(Max('year'))['year__max']
        return super().__init__(data=data, *args, **kwargs)

    def filter_year(self, queryset, name, value):
        try:
            year = int(value)
        except (TypeError, ValueError):
            return queryset.none()
        return queryset.filter(emissions__year=year).prefetch_related(
            Prefetch('emissions', queryset=EmissionsRecord.objects.filter(year=year))
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
