from datetime import timedelta
from decimal import Decimal as D

from django.test import TestCase
from django.utils import timezone

import pandas as pd

from camp.apps.calibrations import trainers, processors
from camp.apps.calibrations.models import CalibrationPair, Calibration
from camp.apps.entries.models import PM25
from camp.apps.monitors.purpleair.models import PurpleAir
from camp.apps.monitors.bam.models import BAM1022


class TestPM25UnivariateLinearRegressionTrainer(TestCase):
    def setUp(self):
        self.colocated = PurpleAir.objects.create(
            name='Colocated Sensor',
            position='POINT(0 0)',
            county='Fresno',
            purple_id=11235,
        )
        self.reference = BAM1022.objects.create(
            name='Reference BAM',
            position='POINT(0.001 0.001)',
            county='Fresno'
        )

        self.pair = CalibrationPair.objects.create(
            colocated=self.colocated,
            reference=self.reference,
            entry_type='PM25',
        )

        now = timezone.now()

        # Create colocated PM2.5 entries
        for i in range(24):
            PM25.objects.create(
                monitor=self.colocated,
                timestamp=now - timezone.timedelta(hours=i),
                value=D(10 + i),
                stage=PM25.Stage.CLEANED,
                sensor='',
            )

        # Create reference PM2.5 entries
        for i in range(24):
            PM25.objects.create(
                monitor=self.reference,
                timestamp=now - timezone.timedelta(hours=i),
                value=D(12 + i),
                stage=PM25.Stage.CLEANED,
                sensor='',
            )

    def test_process_returns_calibration(self):
        trainer = trainers.PM25_UnivariateLinearRegression(pair=self.pair)
        trainer.min_completeness = 0.0  # skip filtering
        calibration = trainer.run()

        assert calibration is not None
        assert calibration.trainer == trainer.name
        assert 0.95 <= calibration.r2 <= 1.0
        assert 'coefs' in calibration.metadata

    def test_trainer_handles_no_data(self):
        self.pair.colocated.pm25_entries.all().delete()
        assert self.pair.colocated.pm25_entries.exists() is False

        trainer = trainers.PM25_UnivariateLinearRegression(pair=self.pair)
        calibration = trainer.run()

        assert calibration is None

    def test_trainer_respects_min_r2(self):
        self.pair.colocated.pm25_entries.update(value=D('100'))

        trainer = trainers.PM25_UnivariateLinearRegression(pair=self.pair)
        calibration = trainer.run()

        assert calibration is None


class TestPM25UnivariateLinearRegressionProcessor(TestCase):
    def setUp(self):
        self.monitor = PurpleAir.objects.create(
            name='Test Monitor',
            position='POINT(0 0)',
            county='Fresno',
            purple_id=11235,
        )

        now = timezone.now()

        self.entry = PM25.objects.create(
            monitor=self.monitor,
            timestamp=now,
            value=D('15.0'),
            stage=PM25.Stage.CLEANED,
            position=self.monitor.position,
        )

    def test_processor_applies_calibration_correctly(self):
        # Create a CalibrationPair
        pair = CalibrationPair.objects.create(
            colocated=self.monitor,
            reference=self.monitor,  # Doesn't really matter for this test
            is_enabled=True,
            entry_type=self.entry.entry_type,
        )

        # Create a Calibration linked to the pair
        Calibration.objects.create(
            pair_id=pair.pk,
            entry_type=self.entry.entry_type,
            trainer=trainers.PM25_UnivariateLinearRegression.name,
            formula='(pm25 * 0.5) + 2',
            intercept=2.0,
            r2=0.99,
            rmse=0.1,
            mae=0.1,
            features=['pm25'],
            metadata={},
            end_time=self.entry.timestamp - timedelta(hours=1),
            start_time=self.entry.timestamp - timedelta(hours=168),
        )

        processor = processors.PM25_UnivariateLinearRegression(self.entry)
        processed = processor.run()

        assert processed is not None
        assert processed.value == D('9.5')

    def test_processor_handles_below_min_threshold(self):
        self.entry.value = D('3.0')
        self.entry.save()

        processor = processors.PM25_UnivariateLinearRegression(self.entry)
        processor.calibration = type('Calib', (), {'formula': '(pm25 * 0.5) + 2'})()

        processed = processor.run()

        assert processed is not None
        assert processed.value == self.entry.value, processors

    def test_processor_ignores_if_no_calibration(self):
        processor = processors.PM25_UnivariateLinearRegression(self.entry)
        processed = processor.run()

        assert processed is None
