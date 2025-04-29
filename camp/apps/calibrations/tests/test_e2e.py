from datetime import timedelta
from decimal import Decimal as D

from django.test import TestCase
from django.utils import timezone

import pandas as pd

from camp.apps.calibrations.models import CalibrationPair, Calibration
from camp.apps.calibrations.trainers.pm25 import PM25_UnivariateLinearRegression as PM25Trainer
from camp.apps.calibrations.processors.pm25 import PM25_UnivariateLinearRegression as PM25Processor
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
        default_stage = self.colocated.get_default_stage(PM25)
        default_sensor = self.colocated.get_default_sensor(PM25)
        for i in range(24):
            PM25.objects.create(
                monitor=self.colocated,
                timestamp=now - timezone.timedelta(hours=i),
                value=D(10 + i),
                stage=default_stage,
                sensor=default_sensor,
            )

        # Create reference PM2.5 entries
        default_stage = self.reference.get_default_stage(PM25)
        default_sensor = self.reference.get_default_sensor(PM25)
        for i in range(24):
            PM25.objects.create(
                monitor=self.reference,
                timestamp=now - timezone.timedelta(hours=i),
                value=D(12 + i),
                stage=default_stage,
                sensor=default_sensor,
            )

    def test_process_returns_calibration(self):
        trainer = PM25Trainer(pair=self.pair)
        calibration = trainer.run()

        assert calibration is not None
        assert calibration.trainer == trainer.name
        assert 0.95 <= calibration.r2 <= 1.0
        assert 'coefs' in calibration.metadata

    def test_trainer_handles_no_data(self):
        self.pair.colocated.pm25_entries.all().delete()
        assert self.pair.colocated.pm25_entries.exists() is False

        trainer = PM25Trainer(pair=self.pair)
        calibration = trainer.run()

        assert calibration is None

    def test_trainer_respects_min_r2(self):
        self.pair.colocated.pm25_entries.update(value=D('100'))

        trainer = PM25Trainer(pair=self.pair)
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
            trainer=PM25Processor.name,
            formula='(pm25 * 0.5) + 2',
            intercept=2.0,
            r2=0.99,
            rmse=0.1,
            mae=0.1,
            features=['pm25'],
            metadata={},
            created=self.entry.timestamp - timedelta(hours=1),
        )

        processor = PM25Processor(self.entry)
        processed = processor.run()

        assert processed is not None
        assert processed.value == D('9.5')

    def test_processor_handles_below_min_threshold(self):
        self.entry.value = D('3.0')
        self.entry.save()

        processor = PM25Processor(self.entry)
        processor.calibration = type('Calib', (), {'formula': '(pm25 * 0.5) + 2'})()

        processed = processor.run()

        assert processed is not None
        assert processed.value == self.entry.value

    def test_processor_ignores_if_no_calibration(self):
        processor = PM25Processor(self.entry)
        processed = processor.run()

        assert processed is None
