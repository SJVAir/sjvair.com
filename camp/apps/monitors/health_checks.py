from datetime import timedelta

from django.db.models import F
from django.utils import timezone
from django.utils.timesince import timesince

from health_check.backends import BaseHealthCheckBackend
from health_check.exceptions import ServiceWarning, ServiceReturnedUnexpectedResult

from camp.apps.monitors.models import Monitor
from camp.apps.monitors.airgradient.models import AirGradient, Place
from camp.apps.monitors.airnow.models import AirNow
from camp.apps.monitors.aqview.models import AQview
from camp.apps.monitors.bam.models import BAM1022
from camp.apps.monitors.purpleair.models import PurpleAir


class MonitorHealthCheck(BaseHealthCheckBackend):
    critical_service = True

    network = None
    model = Monitor
    limit = timedelta(hours=1)

    def identifier(self):
        return f'Air Network: {self.network}'

    def check_status(self):
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
        except Exception as e:
            if isinstance(e, ServiceWarning):
                raise e
            self.add_error(ServiceReturnedUnexpectedResult(e.__class__.__name__), e)


class AirGradientHealthCheck(MonitorHealthCheck):
    network = 'AirGradient'
    model = AirGradient
    limit = timedelta(minutes=10)

    def check_status(self):
        # Only return
        if not Place.objects.exists():
            raise ServiceWarning('No API tokens are configured.')
        return super().check_status()


class AirNowHealthCheck(MonitorHealthCheck):
    network = 'AirNow'
    model = AirNow
    limit = timedelta(hours=3)


class AQviewHealthCheck(MonitorHealthCheck):
    network = 'AQview'
    model = AQview
    limit = timedelta(hours=3)


class CCACBAMHealthCheck(MonitorHealthCheck):
    critical_service = False
    network = 'CCAC BAM-1022'
    model = BAM1022
    limit = timedelta(hours=2)


class PurpleAirHealthCheck(MonitorHealthCheck):
    network = 'PurpleAir'
    model = PurpleAir
    limit = timedelta(minutes=10)

