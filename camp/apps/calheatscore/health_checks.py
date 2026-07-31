import dataclasses
from datetime import timedelta

from django.utils import timezone
from django.utils.timesince import timesince

from health_check.base import HealthCheck
from health_check.exceptions import ServiceWarning, ServiceReturnedUnexpectedResult

from camp.apps.calheatscore.models import CalHeatScore


@dataclasses.dataclass
class CalHeatScoreHealthCheck(HealthCheck):
    # import_calheatscore runs once daily; allow a few hours of slack
    # past the 24h cadence before flagging the feed as stale.
    limit: timedelta = dataclasses.field(default_factory=lambda: timedelta(hours=27), repr=False)

    def __repr__(self):
        return 'CalHeatScore'

    @property
    def labels(self):
        return {'check': 'CalHeatScore'}

    def run(self):
        try:
            latest = CalHeatScore.objects.order_by('-updated_at').first()

            if latest is None:
                raise ServiceWarning('No entries in database.')

            now = timezone.now()
            if now - latest.updated_at > self.limit:
                raise ServiceWarning(f'Last update was {timesince(latest.updated_at)} ago.')
        except ServiceWarning:
            raise
        except Exception as e:
            raise ServiceReturnedUnexpectedResult(e.__class__.__name__) from e
