import django_filters
from resticus.filters import FilterSet

from camp.apps.forecasts.models import Forecast


class ForecastFilter(FilterSet):
    region_id = django_filters.CharFilter(field_name='region__sqid', lookup_expr='exact')

    class Meta:
        model = Forecast
        fields = {
            'forecast_date': ['exact', 'lt', 'lte', 'gt', 'gte'],
            'issued_date': ['exact', 'lt', 'lte', 'gt', 'gte'],
        }
