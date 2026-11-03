from django.conf import settings
from django.utils import timezone

from resticus import generics, http

from camp.apps.forecasts.models import Forecast
from camp.apps.forecasts.scales import get_aqi_forecast_scale, get_burn_status_scale
from camp.apps.forecasts.tasks import ZONE_TO_REGION
from camp.apps.regions.models import Region
from camp.apps.regions.resolve import PlaceError, PlaceNotFound, forecast_zone_for, place_json, resolve_place

from .filters import ForecastFilter
from .serializers import ForecastSerializer, region_json


class ForecastMixin:
    model = Forecast
    serializer_class = ForecastSerializer
    paginate = True

    def get_queryset(self):
        return super().get_queryset().select_related('region')


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


class ForecastPlace(generics.Endpoint):
    """The SJVAPCD forecast for the zone a place falls in (?region_type= &
    ?region=, or ?monitor=; filterable by ?forecast_date and its lt/lte/gt/gte
    variants; defaults to today onward), with the zone and the rule that picked it.
    One forecast per date: the most recently issued."""

    DATE_FILTERS = (
        'forecast_date', 'forecast_date__lt', 'forecast_date__lte',
        'forecast_date__gt', 'forecast_date__gte',
    )

    def get(self, request, *args, **kwargs):
        try:
            place = resolve_place(request.GET)
        except PlaceNotFound as err:
            return http.Http404({'error': str(err)})
        except PlaceError as err:
            return http.Http400({'error': str(err)})

        zone, rule = forecast_zone_for(place)
        forecasts = []
        if zone is not None:
            queryset = Forecast.objects.filter(region=zone).select_related('region')
            if not any(key in request.GET for key in self.DATE_FILTERS):
                today = timezone.now().astimezone(settings.DEFAULT_TIMEZONE).date()
                queryset = queryset.filter(forecast_date__gte=today)
            # Only the date filters: any other would change which zone's rows come back.
            dates = {k: v for k, v in request.GET.items() if k in self.DATE_FILTERS}
            # One row per date: the latest issue (a later publication breaks a tie).
            queryset = (ForecastFilter(dates, queryset=queryset).qs
                .order_by('forecast_date', '-issued_date', '-published_at', '-pk')
                .distinct('forecast_date'))
            forecasts = ForecastSerializer(queryset).serialize()

        response = http.Http200({'data': {
            'place': place_json(place),
            'zone': region_json(zone) if zone else None,
            'rule': rule,
            'forecasts': forecasts,
        }})
        response['Cache-Control'] = 'public, max-age=900'
        return response


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
