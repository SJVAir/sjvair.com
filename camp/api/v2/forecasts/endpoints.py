from django.conf import settings
from django.utils import timezone

from resticus import generics

from camp.apps.forecasts.models import Forecast

from .filters import ForecastFilter
from .serializers import ForecastSerializer


class ForecastMixin:
    model = Forecast
    serializer_class = ForecastSerializer
    paginate = True

    def get_queryset(self):
        return super().get_queryset().select_related('region', 'region__boundary')


class ForecastList(ForecastMixin, generics.ListEndpoint):
    """List SJVAPCD daily air quality forecasts. Defaults to current and future
    forecasts (forecast_date >= today) unless forecast_date is explicitly filtered."""

    filter_class = ForecastFilter

    def get_queryset(self):
        qs = super().get_queryset()
        has_forecast_date_filter = any(
            key == 'forecast_date' or key.startswith('forecast_date__')
            for key in self.request.GET
        )
        if not has_forecast_date_filter:
            today = timezone.now().astimezone(settings.DEFAULT_TIMEZONE).date()
            qs = qs.filter(forecast_date__gte=today)
        return qs


class ForecastDetail(ForecastMixin, generics.DetailEndpoint):
    """Retrieve a single SJVAPCD forecast record."""
    lookup_field = 'sqid'
    lookup_url_kwarg = 'forecast_id'
