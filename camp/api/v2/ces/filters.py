import django_filters
from resticus.filters import FilterSet

from camp.apps.ces.models import CES4, CES5
from camp.apps.regions.models import Region
from camp.apps.regions.querysets import (
    CONTAINED_MIN_FRACTION, OVERLAPS_MIN_FRACTION, area_fraction_inside,
)


WITHIN_MODE_HELP = (
    'With region_id: contained keeps tracts essentially inside the region (99% of their area); '
    'overlaps keeps tracts with at least 1% of their area inside it. Absent: every tract that '
    'touches the region.'
)
MIN_FRACTIONS = {'contained': CONTAINED_MIN_FRACTION, 'overlaps': OVERLAPS_MIN_FRACTION}


def filter_by_region(queryset, sqid, within_mode):
    """Records whose own tract boundary touches (or, with a within_mode, sits inside) the region."""
    try:
        region = Region.all_objects.select_related('boundary').get(sqid=sqid)
    except Region.DoesNotExist:
        return queryset.none()
    try:
        geometry = region.boundary.geometry
    except AttributeError:
        return queryset.none()
    if within_mode in MIN_FRACTIONS:
        return area_fraction_inside(queryset, geometry, MIN_FRACTIONS[within_mode])
    return queryset.filter(boundary__geometry__intersects=geometry)


class CES4Filter(FilterSet):
    # Declared here so `year` shows up in the generated OpenAPI schema; the
    # actual default-to-2020 behavior is applied in CES4Mixin.get_queryset().
    year = django_filters.CharFilter(field_name='boundary__version')
    region_id = django_filters.CharFilter(method='filter_region_id')
    within_mode = django_filters.CharFilter(method='noop', help_text=WITHIN_MODE_HELP)

    def noop(self, queryset, name, value):
        return queryset

    def filter_region_id(self, queryset, name, value):
        return filter_by_region(queryset, value, self.data.get('within_mode'))

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


class CES5Filter(FilterSet):
    region_id = django_filters.CharFilter(method='filter_region_id')
    within_mode = django_filters.CharFilter(method='noop', help_text=WITHIN_MODE_HELP)

    def noop(self, queryset, name, value):
        return queryset

    def filter_region_id(self, queryset, name, value):
        return filter_by_region(queryset, value, self.data.get('within_mode'))

    class Meta:
        model = CES5
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
            'pol_small_ats_p': ['exact', 'lt', 'lte', 'gt', 'gte'],
            'char_diabetes_p': ['exact', 'lt', 'lte', 'gt', 'gte'],
        }
