import pandas as pd
import pytest

from django.test import TestCase
from django.utils import timezone
from datetime import timedelta

from camp.apps.calibrations import trainers
from camp.apps.calibrations.models import CalibrationPair
from camp.apps.entries import models as entry_models
from camp.apps.monitors.models import Monitor

TRAINER_PARAMS = [
    (trainers.PM25_UnivariateLinearRegression, ['pm25']),
    (trainers.PM25_MultivariateLinearRegression, ['pm25', 'temperature', 'humidity']),
]


class TestPM25LinearRegressionTrainers(TestCase):
    def setUp(self):
        self.colocated = Monitor.objects.create(name='Colocated Sensor')
        self.reference = Monitor.objects.create(name='Reference Sensor')

        self.pair = CalibrationPair.objects.create(
            colocated=self.colocated,
            reference=self.reference,
            entry_type='pm25',
        )

        reference_sensor = self.reference.get_default_sensor(entry_models.PM25)
        reference_stage = self.reference.get_default_stage(entry_models.PM25)
        colocated_sensors = {model: self.colocated.get_default_sensor(model) for model in [
            entry_models.PM25, entry_models.Humidity, entry_models.Temperature
        ]}
        colocated_stages = {model: self.colocated.get_default_stage(model) for model in [
            entry_models.PM25, entry_models.Humidity, entry_models.Temperature
        ]}


        timestamps = pd.date_range(end=timezone.now(), periods=24, freq='h')
        for i, ts in enumerate(timestamps):
            entry_models.PM25.objects.create(
                monitor=self.reference,
                timestamp=ts,
                value=12 + i * 0.5,
                stage=reference_stage,
                sensor=reference_sensor,
            )

            entry_models.PM25.objects.create(
                monitor=self.colocated,
                timestamp=ts,
                value=10 + i * 0.5,
                stage=colocated_stages[entry_models.PM25],
                sensor=colocated_sensors[entry_models.PM25],
            )

            entry_models.Temperature.objects.create(
                monitor=self.colocated,
                timestamp=ts,
                value=60 + i * 0.2,
                stage=colocated_stages[entry_models.Temperature],
                sensor=colocated_sensors[entry_models.Temperature],
            )

            entry_models.Humidity.objects.create(
                monitor=self.colocated,
                timestamp=ts,
                value=30 + (i % 10),
                stage=colocated_stages[entry_models.Humidity],
                sensor=colocated_sensors[entry_models.Humidity],
            )

    def test_process_returns_valid_result(self):
        for trainer_class, expected_features in TRAINER_PARAMS:
            trainer = trainer_class(pair=self.pair)
            result = trainer.process()

            assert result is not None
            assert 0.90 <= result.r2 <= 1.0
            for feature in expected_features:
                assert feature in result.metadata['coefs']

    def test_run_creates_calibration(self):
        for trainer_class, expected_features in TRAINER_PARAMS:
            trainer = trainer_class(pair=self.pair)
            calibration = trainer.run()
            calibration.refresh_from_db()

            assert calibration is not None
            assert calibration.trainer == trainer.name
            assert calibration.r2 >= trainer.min_r2
