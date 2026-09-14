from django.test import TestCase

from camp.apps.calibrations.forms import DefaultCalibrationForm
from camp.apps.calibrations.models import DefaultCalibration


class DefaultCalibrationFormChoicesTests(TestCase):
    def _choices(self, monitor_type, entry_type):
        instance = DefaultCalibration(monitor_type=monitor_type, entry_type=entry_type)
        return [value for value, label in DefaultCalibrationForm.get_calibration_choices(instance)]

    def test_pipeline_calibration_processors_are_offered(self):
        choices = self._choices('purpleair', 'pm25')
        assert 'PM25_EPA_Oct2021' in choices

    def test_vozbox_o3_offers_quinncal(self):
        # VOZBox_QuinnCal isn't a pipeline processor (QuinnResearch computes
        # the calibrated value upstream), but it's the configured default
        # calibration and must be selectable in the admin.
        choices = self._choices('vozbox', 'o3')
        assert 'VOZBox_QuinnCal' in choices
        assert 'O3_VOZBox' in choices

    def test_aqlite_o3_offers_hourly_aggregator(self):
        choices = self._choices('aqlite', 'o3')
        assert 'AQLiteHourlyAggregator' in choices

    def test_blank_choice_is_first(self):
        assert self._choices('vozbox', 'o3')[0] == ''
