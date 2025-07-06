from datetime import datetime, timedelta

import pandas as pd

from django.utils.timezone import make_aware
from django.test import TestCase

from camp.apps.monitors.purpleair.models import PurpleAir
from camp.apps.entries.models import PM25
# from camp.apps.qaqc.models import HealthCheck
# from camp.apps.qaqc.evaluator import HealthCheckResult


class HealthCheckTests(TestCase):
    fixtures = ['purple-air.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.get(purple_id=8892)
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
        assert hc.score == 2
        assert hc.variance is not None
        assert hc.correlation is not None

    def test_grade_b_when_sensors_diverge(self):
        values_a = [10 + (i % 3) * 0.1 for i in range(self.samples)]
        values_b = [v * 2 for v in values_a]
        self.create_entries(values_a, values_b)
        hc = self.monitor.run_health_check(self.hour)

        assert hc.grade == 'B'
        assert hc.score == 1

    def test_grade_f_when_both_flatline(self):
        self.create_entries([14.0] * self.samples, [14.0] * self.samples)
        hc = self.monitor.run_health_check(self.hour)

        assert hc.grade == 'F'
        assert hc.score == 0

    def test_grade_b_when_one_sensor_fails(self):
        values_a = [10 + (i % 3) * 0.1 for i in range(self.samples)]
        values_b = [3000 for v in range(self.samples)]

        self.create_entries(values_a=values_a, values_b=values_b)

        hc = self.monitor.run_health_check(self.hour)
        assert hc.grade == 'B'
        assert hc.score == 1

    def test_grade_f_when_data_is_missing(self):
        # Create no entries
        hc = self.monitor.run_health_check(self.hour)

        assert hc.grade == 'F'
        assert hc.score == 0
