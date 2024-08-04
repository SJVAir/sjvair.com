from datetime import timedelta

from django.db.models import F
from django.utils import timezone
from django.utils.timesince import timesince

from health_check.backends import BaseHealthCheckBackend
from health_check.exceptions import ServiceWarning, ServiceReturnedUnexpectedResult

from camp.apps.monitors.models import Monitor
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
            latest = (self.model.objects
                .exclude(latest__isnull=True)
                .order_by('-latest__timestamp')
                .annotate(timestamp=F('latest__timestamp'))
                .values_list('timestamp', flat=True)
                .first()
            )

            if latest is None:
                raise ServiceWarning(f'No entries in database.')

            now = timezone.now()
            if now - latest > self.limit:
                raise ServiceWarning(f'Last entry was {timesince(latest)} ago.')
        except Exception as e:
            if isinstance(e, ServiceWarning):
                raise e
            self.add_error(ServiceReturnedUnexpectedResult(e.__class__.__name__), e)



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

