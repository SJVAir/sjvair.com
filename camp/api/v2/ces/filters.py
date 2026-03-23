from resticus.filters import FilterSet

from camp.apps.ces.models import CES4


class CES4Filter(FilterSet):
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
