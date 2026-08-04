import dataclasses
from datetime import timedelta

import pandas as pd

from django.utils import timezone
from django.utils.timesince import timesince

from health_check.base import HealthCheck
from health_check.exceptions import ServiceReturnedUnexpectedResult, ServiceWarning

from camp.apps.monitors.models import Monitor
from camp.apps.monitors.airgradient.models import AirGradient, Place
from camp.apps.monitors.airnow.models import AirNow
from camp.apps.monitors.aqlite.models import AQLite, Organization
from camp.apps.monitors.aqview.models import AQview
from camp.apps.monitors.bam.models import BAM1022
from camp.apps.monitors.cimis.models import CIMIS
from camp.apps.monitors.purpleair.models import PurpleAir
from camp.apps.monitors.vozbox.models import VOZBox


# General rule: a network's health check `limit` defaults to 3x its
# EXPECTED_INTERVAL -- enough slack to tolerate one missed cycle plus a
# retry without paging, while still catching a genuinely broken feed
# well before LAST_ACTIVE_LIMIT (a separate, per-monitor "still active
# for display" threshold) would. Floored at MIN_LIMIT so fast-cadence
# networks (AirGradient, PurpleAir: 1-2 min intervals) don't page on
# routine jitter -- e.g. a single dropped WiFi packet on consumer
# hardware. Only override `limit` explicitly for a documented,
# network-specific reason beyond that.
DEFAULT_LIMIT_MULTIPLIER = 3
MIN_LIMIT = timedelta(minutes=15)


@dataclasses.dataclass
class MonitorHealthCheck(HealthCheck):
    network: str = dataclasses.field(default='', repr=False)
    model: type = dataclasses.field(default=Monitor, repr=False)
    limit: timedelta = dataclasses.field(default=None, repr=False)

    def __post_init__(self):
        if self.limit is None:
            computed = DEFAULT_LIMIT_MULTIPLIER * pd.to_timedelta(self.model.EXPECTED_INTERVAL)
            self.limit = max(computed, pd.Timedelta(MIN_LIMIT))

    def __repr__(self):
        return self.network

    @property
    def labels(self):
        return {'check': self.network}

    def run(self):
        try:
            if not self.model.objects.exists():
                raise ServiceWarning(f'No {self.network} monitors are configured.')

            # Deliberately not using get_active() here: its cutoff is each
            # model's LAST_ACTIVE_LIMIT, which for some networks (e.g.
            # AirNow, CCAC BAM-1022) is tighter than this check's own
            # `limit`. Filtering on it first would make the check report
            # "no entries" before its own staleness tolerance is even
            # reached. Find the freshest entry across ALL monitors instead,
            # and let `limit` be the only threshold that matters here.
            monitor = (self.model.objects
                .get_queryset()
                .with_last_entry_timestamp()
                .filter(last_entry_timestamp__isnull=False)
                .order_by('-last_entry_timestamp')
                .first()
            )

            if monitor is None:
                raise ServiceWarning(f'No {self.network} monitor has ever reported data.')

            timestamp = monitor.last_entry_timestamp
            now = timezone.now()
            if now - timestamp > self.limit:
                raise ServiceWarning(f'Last {self.network} entry was {timesince(timestamp)} ago.')
        except ServiceWarning:
            raise
        except Exception as e:
            raise ServiceReturnedUnexpectedResult(e.__class__.__name__) from e


@dataclasses.dataclass(repr=False)
class AirGradientHealthCheck(MonitorHealthCheck):
    network: str = dataclasses.field(default='AirGradient', repr=False)
    model: type = dataclasses.field(default=AirGradient, repr=False)

    def run(self):
        if not Place.objects.exists():
            return
        super().run()


@dataclasses.dataclass(repr=False)
class AirNowHealthCheck(MonitorHealthCheck):
    network: str = dataclasses.field(default='AirNow', repr=False)
    model: type = dataclasses.field(default=AirNow, repr=False)


@dataclasses.dataclass(repr=False)
class AQviewHealthCheck(MonitorHealthCheck):
    network: str = dataclasses.field(default='AQview', repr=False)
    model: type = dataclasses.field(default=AQview, repr=False)


@dataclasses.dataclass(repr=False)
class CCACBAMHealthCheck(MonitorHealthCheck):
    network: str = dataclasses.field(default='CCAC BAM-1022', repr=False)
    model: type = dataclasses.field(default=BAM1022, repr=False)

    def run(self):
        if not BAM1022.objects.exists():
            return
        super().run()


@dataclasses.dataclass(repr=False)
class CIMISHealthCheck(MonitorHealthCheck):
    network: str = dataclasses.field(default='CIMIS', repr=False)
    model: type = dataclasses.field(default=CIMIS, repr=False)


@dataclasses.dataclass(repr=False)
class AQLiteHealthCheck(MonitorHealthCheck):
    network: str = dataclasses.field(default='AQLite', repr=False)
    model: type = dataclasses.field(default=AQLite, repr=False)

    def run(self):
        if not Organization.objects.filter(is_enabled=True).exists():
            return
        super().run()


@dataclasses.dataclass(repr=False)
class PurpleAirHealthCheck(MonitorHealthCheck):
    network: str = dataclasses.field(default='PurpleAir', repr=False)
    model: type = dataclasses.field(default=PurpleAir, repr=False)


@dataclasses.dataclass(repr=False)
class VOZBoxHealthCheck(MonitorHealthCheck):
    network: str = dataclasses.field(default='VOZbox', repr=False)
    model: type = dataclasses.field(default=VOZBox, repr=False)

    # Override: upstream only publishes once an hour (~5 min after each
    # hour closes, dated for the *previous* hour), so a reading can be
    # up to ~65 min old before it's even available to us. 3x
    # EXPECTED_INTERVAL (10 min) would be 30 min, which would page on
    # totally normal hourly batching, not an actual outage.
    limit: timedelta = dataclasses.field(default_factory=lambda: timedelta(hours=2), repr=False)
