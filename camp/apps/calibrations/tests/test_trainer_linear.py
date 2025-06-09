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

        colocated_stages = {model: self.colocated.get_default_stage(model) for model in [
            entry_models.PM25, entry_models.Humidity, entry_models.Temperature
        ]}


        timestamps = pd.date_range(end=timezone.now(), periods=24, freq='h')
        for i, ts in enumerate(timestamps):
            entry_models.PM25.objects.create(
                monitor=self.reference,
                timestamp=ts,
                value=12 + i * 0.5,
                stage=entry_models.PM25.Stage.CLEANED,
                sensor='',
            )

            entry_models.PM25.objects.create(
                monitor=self.colocated,
                timestamp=ts,
                value=10 + i * 0.5,
                stage=colocated_stages[entry_models.PM25],
                sensor='',
            )

            entry_models.Temperature.objects.create(
                monitor=self.colocated,
                timestamp=ts,
                value=60 + i * 0.2,
                stage=colocated_stages[entry_models.Temperature],
                sensor='',
            )

            entry_models.Humidity.objects.create(
                monitor=self.colocated,
                timestamp=ts,
                value=30 + (i % 10),
                stage=colocated_stages[entry_models.Humidity],
                sensor='',
            )

    def test_process_returns_valid_result(self):
        for trainer_class, expected_features in TRAINER_PARAMS:
            trainer = trainer_class(pair=self.pair)
            trainer.min_completeness = 0.0
            result = trainer.process()

            assert result is not None
            assert 0.90 <= result.r2 <= 1.0
            for feature in expected_features:
                assert feature in result.metadata['coefs']

    def test_run_creates_calibration(self):
        for trainer_class, expected_features in TRAINER_PARAMS:
            trainer = trainer_class(pair=self.pair)
            trainer.min_completeness = 0.0
            calibration = trainer.run()
            calibration.refresh_from_db()

            assert calibration is not None
            assert calibration.trainer == trainer.name
            assert calibration.r2 >= trainer.min_r2

    def test_multivariate_trainer_skips_missing_data(self):
        # Nuke the Humidity entries created as part of the setup.
        entry_models.Humidity.objects.all().delete()

        # Initialize trainer
        trainer = trainers.PM25_MultivariateLinearRegression(pair=self.pair)

        # Fetch feature and target data
        feature_df = trainer.get_feature_dataframe(days=7)
        target_series = trainer.get_target_series(days=7)

        # Assert that data is missing and correctly detected.
        assert 'humidity' in feature_df.columns
        assert feature_df['humidity'].isna().all()
        assert trainer.has_required_data(feature_df, target_series) is False
