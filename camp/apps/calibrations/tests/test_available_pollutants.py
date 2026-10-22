from django.test import TestCase

from camp.apps.calibrations.models import DefaultCalibration


class AvailablePollutantsTests(TestCase):
    fixtures = ['default-calibrations.yaml']

    def test_fixture_publishes_pm25_and_o3(self):
        assert DefaultCalibration.objects.available_pollutants() == ['o3', 'pm25']

    def test_adding_a_row_makes_it_available(self):
        DefaultCalibration.objects.create(monitor_type='airnow', entry_type='no2', calibration='')
        assert 'no2' in DefaultCalibration.objects.available_pollutants()

    def test_disabled_monitor_types_are_excluded(self):
        DefaultCalibration.objects.create(monitor_type='airnow', entry_type='no2', calibration='')
        with self.settings(MONITOR_ENABLED_TYPES=['purpleair']):
            assert 'no2' not in DefaultCalibration.objects.available_pollutants()
