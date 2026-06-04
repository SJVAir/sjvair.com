import dataclasses
from datetime import timedelta

from django.utils import timezone
from django.utils.timesince import timesince

from health_check.base import HealthCheck
from health_check.exceptions import ServiceWarning, ServiceReturnedUnexpectedResult

from camp.apps.monitors.models import Monitor
from camp.apps.monitors.airgradient.models import AirGradient, Place
from camp.apps.monitors.airnow.models import AirNow
from camp.apps.monitors.aqview.models import AQview
from camp.apps.monitors.bam.models import BAM1022
from camp.apps.monitors.purpleair.models import PurpleAir


@dataclasses.dataclass
class MonitorHealthCheck(HealthCheck):
    network: str = dataclasses.field(default='', repr=False)
    model: type = dataclasses.field(default=Monitor, repr=False)
    limit: timedelta = dataclasses.field(default_factory=lambda: timedelta(hours=1), repr=False)

    def __repr__(self):
        return self.network

    @property
    def labels(self):
        return {'check': self.network}

    def run(self):
        try:
            monitor = (self.model.objects
                .get_active()
                .with_last_entry_timestamp()
                .order_by('-last_entry_timestamp')
                .first()
            )

            if monitor is None:
                raise ServiceWarning('No entries in database.')

            timestamp = monitor.last_entry_timestamp
            now = timezone.now()
            if now - timestamp > self.limit:
                raise ServiceWarning(f'Last entry was {timesince(timestamp)} ago.')
        except ServiceWarning:
            raise
        except Exception as e:
            raise ServiceReturnedUnexpectedResult(e.__class__.__name__) from e


@dataclasses.dataclass(repr=False)
class AirGradientHealthCheck(MonitorHealthCheck):
    network: str = dataclasses.field(default='AirGradient', repr=False)
    model: type = dataclasses.field(default=AirGradient, repr=False)
    limit: timedelta = dataclasses.field(default_factory=lambda: timedelta(minutes=10), repr=False)

    def run(self):
        if not Place.objects.exists():
            raise ServiceWarning('No API tokens are configured.')
        super().run()


@dataclasses.dataclass(repr=False)
class AirNowHealthCheck(MonitorHealthCheck):
    network: str = dataclasses.field(default='AirNow', repr=False)
    model: type = dataclasses.field(default=AirNow, repr=False)
    limit: timedelta = dataclasses.field(default_factory=lambda: timedelta(hours=3), repr=False)


@dataclasses.dataclass(repr=False)
class AQviewHealthCheck(MonitorHealthCheck):
    network: str = dataclasses.field(default='AQview', repr=False)
    model: type = dataclasses.field(default=AQview, repr=False)
    limit: timedelta = dataclasses.field(default_factory=lambda: timedelta(hours=3), repr=False)


@dataclasses.dataclass(repr=False)
class CCACBAMHealthCheck(MonitorHealthCheck):
    network: str = dataclasses.field(default='CCAC BAM-1022', repr=False)
    model: type = dataclasses.field(default=BAM1022, repr=False)
    limit: timedelta = dataclasses.field(default_factory=lambda: timedelta(hours=2), repr=False)


@dataclasses.dataclass(repr=False)
class PurpleAirHealthCheck(MonitorHealthCheck):
    network: str = dataclasses.field(default='PurpleAir', repr=False)
    model: type = dataclasses.field(default=PurpleAir, repr=False)
    limit: timedelta = dataclasses.field(default_factory=lambda: timedelta(minutes=10), repr=False)
