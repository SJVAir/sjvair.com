from datetime import datetime, timedelta
from unittest.mock import patch

import pandas as pd

from django.utils.timezone import make_aware
from django.test import TestCase

from camp.apps.monitors.purpleair.models import PurpleAir
from camp.apps.entries.models import PM25
from camp.apps.qaqc.evaluator import SanityChecks
from camp.apps.qaqc.models import HealthCheck


class HealthCheckTests(TestCase):
    fixtures = ['purple-air.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.get(sensor_id=8892)
        self.hour = make_aware(datetime(2025, 7, 4, 13, 0, 0))
        self.sensor_keys = self.monitor.ENTRY_CONFIG[PM25]['sensors']

        self.interval = pd.Timedelta(self.monitor.EXPECTED_INTERVAL)
        self.samples = int(pd.Timedelta('1h') / self.interval)

    def create_entries(self, values_a, values_b):
        now = self.hour
        a_sensor, b_sensor = self.sensor_keys
        for i, (a_val, b_val) in enumerate(zip(values_a, values_b)):
            timestamp = now + (i * self.interval)
            PM25.objects.create(
                monitor=self.monitor,
                sensor=a_sensor,
                timestamp=timestamp,
                value=a_val,
                stage=PM25.Stage.RAW
            )
            PM25.objects.create(
                monitor=self.monitor,
                sensor=b_sensor,
                timestamp=timestamp,
                value=b_val,
                stage=PM25.Stage.RAW
            )

    def test_grade_a_when_both_sensors_agree(self):
        values_a = [10 + (i % 3) * 0.1 for i in range(self.samples)]
        values_b = [v + 0.5 for v in values_a]
        self.create_entries(values_a=values_a, values_b=values_b)
        hc = self.monitor.run_health_check(self.hour)

        assert hc.grade == 'A'
        assert hc.score == 3
        assert hc.rpd_means is not None
        assert hc.rpd_pairwise is not None
        assert hc.correlation is not None

    def test_grade_b_when_sensors_diverge(self):
        values_a = [10 + (i % 3) * 0.1 for i in range(self.samples)]
        values_b = [v * 2 for v in values_a]
        self.create_entries(values_a, values_b)
        hc = self.monitor.run_health_check(self.hour)

        assert hc.grade == 'B'
        assert hc.score == 2

    def test_grade_f_when_both_flatline(self):
        self.create_entries([14.0] * self.samples, [14.0] * self.samples)
        hc = self.monitor.run_health_check(self.hour)

        assert hc.grade == 'F'
        assert hc.score == 0

    def test_grade_b_when_one_sensor_fails(self):
        values_a = [10 + (i % 3) * 0.1 for i in range(self.samples)]
        values_b = [3000 for _ in range(self.samples)]

        self.create_entries(values_a=values_a, values_b=values_b)

        hc = self.monitor.run_health_check(self.hour)
        assert hc.grade == 'C'
        assert hc.score == 1

    def test_grade_f_when_data_is_missing(self):
        # Create no entries
        hc = self.monitor.run_health_check(self.hour)

        assert hc.grade == 'F'
        assert hc.score == 0

    def test_grade_does_not_crash_when_rpd_pairwise_is_none(self):
        # Both channels at zero produces rpd_pairwise=None (0/0); get_score() must not crash
        self.create_entries([0.0] * self.samples, [0.0] * self.samples)
        hc = self.monitor.run_health_check(self.hour)

        assert hc.rpd_pairwise is None
        assert hc.score in (0, 1, 2)  # grade B at best — not A, since rpd_pairwise is unknown

    def test_monitor_health_grade_updated(self):
        # Create an old health check
        HealthCheck.objects.create(
            monitor=self.monitor,
            hour=self.hour - timedelta(hours=2),
            score=2,
            rpd_means=0.08,
            rpd_pairwise=0.15,
            correlation=0.98
        )

        # Create some valid data and re-run the health check
        values_a = [10 + (i % 3) * 0.1 for i in range(self.samples)]
        values_b = [v + 0.5 for v in values_a]
        self.create_entries(values_a=values_a, values_b=values_b)
        hc = self.monitor.run_health_check(self.hour)

        # Ensure the monitor's health object has been updated
        self.monitor.refresh_from_db()
        assert self.monitor.health_id == hc.pk


class SanityChecksOkTests(TestCase):
    def _make_sanity(self, results):
        """Build a SanityChecks with pre-set results, bypassing __post_init__."""
        sc = object.__new__(SanityChecks)
        sc.results = results
        return sc

    def test_all_true_is_ok(self):
        sc = self._make_sanity({'max': True, 'flatline': True, 'completeness': True})
        assert sc.ok is True

    def test_any_false_is_not_ok(self):
        sc = self._make_sanity({'max': True, 'flatline': False, 'completeness': True})
        assert sc.ok is False

    def test_none_values_are_skipped(self):
        # None means indeterminate — should not count as failure
        sc = self._make_sanity({'max': None, 'flatline': None, 'completeness': True})
        assert sc.ok is True

    def test_none_mixed_with_false_still_fails(self):
        sc = self._make_sanity({'max': None, 'flatline': False, 'completeness': True})
        assert sc.ok is False


class ChannelSanityTests(TestCase):
    fixtures = ['purple-air.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.get(sensor_id=8892)
        self.hour = make_aware(datetime(2025, 7, 4, 13, 0, 0))

    def test_channel_sanity_true_when_all_none(self):
        # Sanity fields are null (health check never fully evaluated) — vacuously passes
        hc = HealthCheck.objects.create(monitor=self.monitor, hour=self.hour, score=0)
        assert hc.channel_a_sanity is True
        assert hc.channel_b_sanity is True

    def test_channel_sanity_false_when_any_false(self):
        hc = HealthCheck.objects.create(
            monitor=self.monitor, hour=self.hour, score=0,
            sanity_max_a=True, sanity_flatline_a=False, sanity_completeness_a=True,
        )
        assert hc.channel_a_sanity is False

    def test_channel_sanity_true_when_all_true(self):
        hc = HealthCheck.objects.create(
            monitor=self.monitor, hour=self.hour, score=3,
            sanity_max_a=True, sanity_flatline_a=True, sanity_completeness_a=True,
        )
        assert hc.channel_a_sanity is True


class HourlyHealthChecksTaskTests(TestCase):
    fixtures = ['purple-air.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.get(sensor_id=8892)
        self.now = make_aware(datetime(2025, 7, 4, 13, 15, 0))
        self.this_hour = self.now.replace(minute=0)
        self.sensor_a, self.sensor_b = self.monitor.ENTRY_CONFIG[PM25]['sensors']

    def create_hour_entries(self, hour):
        for i in range(6):
            timestamp = hour + timedelta(minutes=10 * i)
            for sensor in (self.sensor_a, self.sensor_b):
                PM25.objects.create(
                    monitor=self.monitor,
                    sensor=sensor,
                    timestamp=timestamp,
                    value=10.0,
                    stage=PM25.Stage.RAW,
                )

    def run_task(self):
        from camp.apps.qaqc.tasks import hourly_health_checks
        with patch('camp.apps.qaqc.tasks.timezone.now', return_value=self.now):
            hourly_health_checks.call_local()

    def test_scores_previous_hour(self):
        last_hour = self.this_hour - timedelta(hours=1)
        self.create_hour_entries(last_hour)

        self.run_task()

        assert HealthCheck.objects.filter(monitor=self.monitor, hour=last_hour).exists()

    def test_lookback_scores_late_arriving_hour_once(self):
        # Hour H-2 had no entries when it was first scored (e.g. a late
        # upstream publish); the data has since landed, so the next run
        # should pick it up.
        late_hour = self.this_hour - timedelta(hours=2)
        self.create_hour_entries(late_hour)

        self.run_task()
        assert HealthCheck.objects.filter(monitor=self.monitor, hour=late_hour).count() == 1

        # Already-scored lookback hours are left alone on subsequent runs.
        with patch('camp.apps.qaqc.tasks.monitor_health_check') as mock_check:
            with patch('camp.apps.qaqc.tasks.timezone.now', return_value=self.now):
                from camp.apps.qaqc.tasks import hourly_health_checks
                hourly_health_checks.call_local()
        assert mock_check.call_count == 0

    def test_lookback_ignores_hours_beyond_window(self):
        old_hour = self.this_hour - timedelta(hours=5)
        self.create_hour_entries(old_hour)

        self.run_task()

        assert not HealthCheck.objects.filter(monitor=self.monitor, hour=old_hour).exists()
