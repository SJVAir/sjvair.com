from django.test import TestCase
from django.utils import timezone
from datetime import timedelta

from camp.apps.entries import models as entry_models
from camp.apps.monitors.models import Monitor
from camp.apps.calibrations.models import CalibrationPair
from camp.apps.calibrations.trainers.pm25 import PM25_UnivariateLinearRegression

import pandas as pd


class PM25TrainerTests(TestCase):
    def setUp(self):
        # Create colocated and reference monitors
        self.colocated = Monitor.objects.create(name='Colocated Sensor')
        self.reference = Monitor.objects.create(name='Reference Sensor')

        # Create a calibration pair
        self.pair = CalibrationPair.objects.create(
            colocated=self.colocated,
            reference=self.reference,
            entry_type='pm25',
        )

        # Insert some dummy PM2.5 entries for colocated
        timestamps = pd.date_range(end=timezone.now(), periods=24, freq='h')
        for i, ts in enumerate(timestamps):
            entry_models.PM25.objects.create(
                monitor=self.colocated,
                timestamp=ts,
                value=10 + i * 0.5,  # Linearly increasing
                stage='raw'
            )

        # Insert matching dummy PM2.5 entries for reference
        for i, ts in enumerate(timestamps):
            entry_models.PM25.objects.create(
                monitor=self.reference,
                timestamp=ts,
                value=12 + i * 0.5,  # Linearly increasing but offset
                stage='raw'
            )

    def test_process_returns_valid_result(self):
        trainer = PM25_UnivariateLinearRegression(pair=self.pair)
        result = trainer.process()
        print(result)

        assert result is not None
        assert 0.95 <= result.r2 <= 1.0
        assert 'value' in result.metadata['coefs']

    def test_run_creates_calibration(self):
        trainer = PM25_UnivariateLinearRegression(pair=self.pair)
        calibration = trainer.run()
        calibration.refresh_from_db()

        assert calibration is not None
        assert calibration.trainer == trainer.name
        assert calibration.r2 >= trainer.min_r2
