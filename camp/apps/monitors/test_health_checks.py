from datetime import timedelta

import pytest
from django.contrib.gis.geos import Point
from django.test import TestCase
from django.utils import timezone

from health_check.exceptions import ServiceWarning

from camp.apps.entries.models import PM25, Temperature
from camp.apps.monitors.airnow.models import AirNow
from camp.apps.monitors.aqview.models import AQview
from camp.apps.monitors.cimis.models import CIMIS
from camp.apps.monitors.vozbox.models import VOZBox
from camp.apps.monitors.health_checks import (
    AirGradientHealthCheck,
    AirNowHealthCheck,
    AQLiteHealthCheck,
    AQviewHealthCheck,
    CIMISHealthCheck,
    PurpleAirHealthCheck,
    VOZBoxHealthCheck,
)


def make_airnow():
    return AirNow.objects.create(
        name='Test AirNow',
        position=Point(-119.8, 36.7),
        location='outside',
    )


def make_cimis():
    return CIMIS.objects.create(
        name='Test CIMIS',
        station_number='2',
        position=Point(-119.8, 36.7),
        location='outside',
    )


class MonitorHealthCheckTests(TestCase):
    def test_raises_when_no_monitors_configured(self):
        check = AirNowHealthCheck()

        with pytest.raises(ServiceWarning, match='No AirNow monitors are configured.'):
            check.run()

    def test_raises_when_monitors_exist_but_never_reported(self):
        make_airnow()
        check = AirNowHealthCheck()

        with pytest.raises(ServiceWarning, match='No AirNow monitor has ever reported data.'):
            check.run()

    def test_passes_when_recently_reported(self):
        monitor = make_airnow()
        monitor.create_entry(
            PM25,
            stage=PM25.Stage.CLEANED,
            processor='PM25_FEM_Cleaner',
            timestamp=timezone.now(),
            value=10,
        )

        check = AirNowHealthCheck()
        check.run()

    def test_raises_when_stale_beyond_own_limit(self):
        monitor = make_airnow()
        monitor.create_entry(
            PM25,
            stage=PM25.Stage.CLEANED,
            processor='PM25_FEM_Cleaner',
            timestamp=timezone.now() - timedelta(hours=4),
            value=10,
        )

        check = AirNowHealthCheck()
        with pytest.raises(ServiceWarning, match='Last AirNow entry was'):
            check.run()

    def test_reports_staleness_within_own_limit_even_past_last_active_limit(self):
        """
        Regression test: AirNow's LAST_ACTIVE_LIMIT (1.5h) is tighter than its
        health check `limit` (3h). A monitor stale by 2h should still surface
        the informative "Last entry was X ago" message, not the misleading
        "no monitor has ever reported" message that get_active()-based
        filtering used to produce once past LAST_ACTIVE_LIMIT.
        """
        monitor = make_airnow()
        monitor.create_entry(
            PM25,
            stage=PM25.Stage.CLEANED,
            processor='PM25_FEM_Cleaner',
            timestamp=timezone.now() - timedelta(hours=2),
            value=10,
        )

        check = AirNowHealthCheck()
        check.run()  # within the 3h limit -- should not raise

    def test_aqview_limit_equal_to_last_active_limit_still_works(self):
        monitor = AQview.objects.create(
            name='Test AQview',
            position=Point(-119.8, 36.7),
            location='outside',
        )
        monitor.create_entry(
            PM25,
            stage=PM25.Stage.CLEANED,
            processor='PM25_FEM_Cleaner',
            timestamp=timezone.now(),
            value=10,
        )

        check = AQviewHealthCheck()
        check.run()

    def test_vozbox_tolerates_normal_hourly_batch_latency(self):
        """
        Regression test: upstream's hourly batching means a reading can
        be up to ~65 min old before it's even available. A monitor
        stale by 70 min -- normal, expected latency -- must not trip
        the health check under the 2h override, even though it would
        have failed under the computed 3x default (30 min).
        """
        monitor = VOZBox.objects.create(
            sensor_id='e00fce68testlatency',
            name='Test VOZbox',
            position=Point(-119.8, 36.7),
            location='outside',
        )
        monitor.create_entry(
            PM25,
            stage=PM25.Stage.CLEANED,
            sensor='a',
            timestamp=timezone.now() - timedelta(minutes=70),
            value=10,
        )

        check = VOZBoxHealthCheck()
        check.run()  # within the 2h override -- should not raise


class CIMISHealthCheckTests(TestCase):
    def test_raises_when_no_monitors_configured(self):
        check = CIMISHealthCheck()

        with pytest.raises(ServiceWarning, match='No CIMIS monitors are configured.'):
            check.run()

    def test_raises_when_monitors_exist_but_never_reported(self):
        make_cimis()
        check = CIMISHealthCheck()

        with pytest.raises(ServiceWarning, match='No CIMIS monitor has ever reported data.'):
            check.run()

    def test_passes_when_recently_reported(self):
        monitor = make_cimis()
        monitor.create_entry(
            Temperature,
            stage=Temperature.Stage.RAW,
            timestamp=timezone.now(),
            celsius=20,
        )

        check = CIMISHealthCheck()
        check.run()

    def test_raises_when_stale_beyond_limit(self):
        monitor = make_cimis()
        monitor.create_entry(
            Temperature,
            stage=Temperature.Stage.RAW,
            timestamp=timezone.now() - timedelta(hours=4),
            celsius=20,
        )

        check = CIMISHealthCheck()
        with pytest.raises(ServiceWarning, match='Last CIMIS entry was'):
            check.run()


class HealthCheckLimitTests(TestCase):
    def test_default_limit_is_3x_expected_interval(self):
        check = AirNowHealthCheck()
        assert check.limit == timedelta(hours=1) * 3

    def test_limit_floors_at_15_minutes_for_fast_cadence_networks(self):
        # AirGradient's EXPECTED_INTERVAL is 1 min; 3x would be 3 min,
        # which the 15-min floor exists specifically to avoid.
        check = AirGradientHealthCheck()
        assert check.limit == timedelta(minutes=15)

    def test_limit_floors_at_15_minutes_for_purpleair(self):
        # PurpleAir's EXPECTED_INTERVAL is 2 min; 3x would be 6 min.
        check = PurpleAirHealthCheck()
        assert check.limit == timedelta(minutes=15)

    def test_aqlite_lands_exactly_on_the_floor(self):
        # AQLite's EXPECTED_INTERVAL is 5 min; 3x is exactly 15 min.
        check = AQLiteHealthCheck()
        assert check.limit == timedelta(minutes=15)

    def test_vozbox_overrides_the_computed_default(self):
        # VOZBox's EXPECTED_INTERVAL (10 min) reflects the true per-row
        # device cadence and stays that way for QA/alerts/training, but
        # upstream only publishes in hourly batches with up to ~65 min
        # of latency -- so the health check needs a wider, explicit
        # limit rather than the computed 3x default (30 min).
        check = VOZBoxHealthCheck()
        assert check.limit == timedelta(hours=2)
