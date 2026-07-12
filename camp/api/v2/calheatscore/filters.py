from resticus.filters import FilterSet

from camp.apps.calheatscore.models import CalHeatScore


class CalHeatScoreFilter(FilterSet):
    class Meta:
        model = CalHeatScore
        fields = {
            'date': ['exact', 'gte', 'lte'],
            'score': ['exact', 'gte', 'lte'],
        }
