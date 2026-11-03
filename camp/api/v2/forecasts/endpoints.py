from django.conf import settings
from django.utils import timezone

from resticus import generics, http

from camp.apps.forecasts.models import Forecast
from camp.apps.forecasts.scales import get_aqi_forecast_scale, get_burn_status_scale
from camp.apps.forecasts.tasks import ZONE_TO_REGION
from camp.apps.regions.models import Region

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


class ForecastMeta(generics.Endpoint):
    """The forecast scales (AQI and burn status) and the forecast zones, each
    with the region it maps to (null when that region isn't imported)."""

    def get(self, request, *args, **kwargs):
        scales = [get_aqi_forecast_scale(), get_burn_status_scale()]
        regions = {
            (region.type, region.name): region
            for region in Region.objects.filter(
                name__in=[name for _, name in ZONE_TO_REGION.values()],
            )
        }
        zones = []
        for zone_name, key in ZONE_TO_REGION.items():
            region = regions.get(key)
            zones.append({
                'name': zone_name,
                'region': {
                    'id': region.sqid,
                    'type': region.type,
                    'external_id': region.external_id,
                    'name': region.name,
                } if region else None,
            })
        response = http.Http200({'data': {
            'scales': {scale.id: scale.to_json() for scale in scales},
            'zones': zones,
        }})
        response['Cache-Control'] = 'public, max-age=3600'
        return response
