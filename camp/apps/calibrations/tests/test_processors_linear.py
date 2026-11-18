from datetime import timedelta
from decimal import Decimal as D

from django.test import TestCase
from django.utils import timezone

from camp.apps.calibrations import processors
from camp.apps.calibrations.models import CalibrationPair, Calibration
from camp.apps.entries.models import PM25
from camp.apps.monitors.bam.models import BAM1022
from camp.apps.monitors.purpleair.models import PurpleAir


class BaseLinearProcessorTest(TestCase):
    def setUp(self):
        self.colocated = PurpleAir.objects.create(
            name='Colocated Sensor',
            position='POINT(0 0)',
            county='Fresno',
            sensor_id=11235,
        )
        self.reference = BAM1022.objects.create(
            name='Reference BAM',
            position='POINT(0.001 0.001)',
            county='Fresno'
        )

        self.pair = CalibrationPair.objects.create(
            colocated=self.colocated,
            reference=self.reference,
            entry_type='pm25',
        )

        self.timestamp = timezone.now()

    def create_calibration(self, **kwargs):
        defaults = {
            'pair_id': self.pair.pk,
            'entry_type': PM25.entry_type,
            'formula': 'pm25',
            'trainer': 'TestTrainer',
            'r2': 0.99,
            'metadata': {},
            'end_time': self.timestamp - timedelta(hours=1),
            'start_time': self.timestamp - timedelta(hours=168),
        }
        defaults.update(kwargs)
        return Calibration.objects.create(**defaults)

    def create_pm25_entry(self, **kwargs):
        defaults = {
            'monitor_id': self.colocated.pk,
            'timestamp': self.timestamp,
            'position': self.colocated.position,
            'sensor': '',
            'stage': self.colocated.get_default_stage(PM25),
        }
        defaults.update(kwargs)
        return PM25.objects.create(**defaults)


class TestPM25UnivariateLinearExpressionProcessor(BaseLinearProcessorTest):
    def test_process_returns_calibrated_entry(self):
        calibration = self.create_calibration(
            trainer=processors.PM25_UnivariateLinearRegression.name,
            formula='pm25 * 2'
        )
        entry = self.create_pm25_entry(value=D('10.0'))
        processor = processors.PM25_UnivariateLinearRegression(entry=entry)
        result = processor.run()

        assert result is not None
        assert result.value == D('20.0')
        assert result.calibration_id == calibration.pk
        assert result.stage == PM25.Stage.CALIBRATED

    def test_below_threshold_returns_raw_value(self):
        calibration = self.create_calibration(
            trainer=processors.PM25_UnivariateLinearRegression.name,
            formula='pm25 * 2',
        )
        entry = self.create_pm25_entry(value=D('4.0'))  # Below min_required_value 5.0
        processor = processors.PM25_UnivariateLinearRegression(entry=entry)

        result = processor.run()

        assert result is not None
        assert result.value == entry.value  # Should just pass through the raw value


class TestPM25MultivariateLinearExpressionProcessor(BaseLinearProcessorTest):
    def test_process_returns_calibrated_entry(self):
        calibration = self.create_calibration(
            trainer=processors.PM25_MultivariateLinearRegression.name,
            formula='pm25 + temperature + humidity',
        )
        entry = self.create_pm25_entry(value=D('10.0'))

        processor = processors.PM25_MultivariateLinearRegression(entry=entry)
        processor.context = {
            'pm25': D('10.0'),
            'temperature': D('25.0'),
            'humidity': D('30.0'),
        }

        result = processor.run()

        assert result is not None
        assert result.value == D('65.0')  # 10 + 25 + 30
        assert result.calibration_id == calibration.pk
        assert result.stage == PM25.Stage.CALIBRATED

    def test_below_threshold_returns_raw_value(self):
        calibration = self.create_calibration(
            trainer=processors.PM25_MultivariateLinearRegression.name,
            formula='pm25 + temperature + humidity',
        )
        entry = self.create_pm25_entry(value=D('4.0'))  # Below threshold

        processor = processors.PM25_MultivariateLinearRegression(entry=entry)
        processor.context = {
            'pm25': D('4.0'),
            'temperature': D('25.0'),
            'humidity': D('30.0'),
        }

        result = processor.run()

        assert result is not None
        assert result.value == entry.value


class TestOutOfRangeRegressionOutput(BaseLinearProcessorTest):
    def run_processor(self, formula, value='10.0'):
        self.create_calibration(
            trainer=processors.PM25_UnivariateLinearRegression.name,
            formula=formula,
        )
        entry = self.create_pm25_entry(value=D(value))
        return entry, processors.PM25_UnivariateLinearRegression(entry=entry).run()

    def test_overflowing_value_yields_no_entry(self):
        entry, result = self.run_processor('pm25 * 90.36 + 99999')
        assert result is None
        assert PM25.objects.filter(monitor_id=self.colocated.pk, stage=PM25.Stage.CALIBRATED).count() == 0

    def test_value_above_plausible_max_yields_no_entry(self):
        entry, result = self.run_processor('pm25 * 200')  # 2000 > 1500
        assert result is None

    def test_negative_value_yields_no_entry(self):
        entry, result = self.run_processor('pm25 - 50')
        assert result is None

    def test_value_at_max_is_kept(self):
        entry, result = self.run_processor('pm25 * 150')  # 1500
        assert result is not None
        assert result.value == D('1500')

    def test_out_of_range_logs_warning(self):
        with self.assertLogs('camp.apps.calibrations.core.processors.ml.linear', level='WARNING') as logs:
            self.run_processor('pm25 * 200')
        assert 'out-of-range' in logs.output[0]
