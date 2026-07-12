import dataclasses
from datetime import timedelta

from django.utils import timezone
from django.utils.timesince import timesince

from health_check.base import HealthCheck
from health_check.exceptions import ServiceWarning, ServiceReturnedUnexpectedResult

from camp.apps.forecasts.models import Forecast


@dataclasses.dataclass
class ForecastsHealthCheck(HealthCheck):
    # The feed updates once daily (~4:30pm Pacific); fetch_forecasts runs across
    # a multi-hour window (23,0,1,2 UTC) to absorb DST, so the worst-case gap
    # between two successful runs is the ~24 hour cadence plus that window.
    limit: timedelta = dataclasses.field(default_factory=lambda: timedelta(hours=27), repr=False)

    def __repr__(self):
        return 'SJVAPCD Forecast'

    @property
    def labels(self):
        return {'check': 'SJVAPCD Forecast'}

    def run(self):
        try:
            forecast = Forecast.objects.order_by('-created').first()

            if forecast is None:
                raise ServiceWarning('No forecasts in database.')

            now = timezone.now()
            if now - forecast.created > self.limit:
                raise ServiceWarning(f'Last forecast was ingested {timesince(forecast.created)} ago.')
        except ServiceWarning:
            raise
        except Exception as e:
            raise ServiceReturnedUnexpectedResult(e.__class__.__name__) from e
