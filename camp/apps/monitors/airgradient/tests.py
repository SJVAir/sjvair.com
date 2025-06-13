from django.test import TestCase
from unittest.mock import patch

from camp.apps.monitors.airgradient.api import AirGradientAPI


class AirGradientAPITests(TestCase):
    def setUp(self):
        self.api = AirGradientAPI(token='abc123')

    @patch('camp.apps.monitors.airgradient.api.requests.request')
    def test_ping(self, mock_request):
        mock_request.return_value.ok = True
        response = self.api.ping()
        assert response is True

    @patch('camp.apps.monitors.airgradient.api.requests.request')
    def test_get_world_current_measures(self, mock_request):
        mock_response = {'data': [{'locationId': 123, 'pm02': 5.2}]}
        mock_request.return_value.json.return_value = mock_response
        response = self.api.get_world_current_measures()
        assert response == mock_response

    @patch('camp.apps.monitors.airgradient.api.requests.request')
    def test_get_current_measures(self, mock_request):
        mock_response = {
            'locationId': 42,
            'pm02': 7.8,
            'timestamp': '2024-05-05T12:00:00Z',
        }
        mock_request.return_value.json.return_value = mock_response
        response = self.api.get_current_measures(location_id=42)
        assert response['locationId'] == 42
        assert response['pm02'] == 7.8

    @patch('camp.apps.monitors.airgradient.api.requests.request')
    def test_get_raw_measures_with_range(self, mock_request):
        mock_response = {'data': [{'timestamp': '2024-05-05T12:00:00Z', 'pm02': 10.5}]}
        mock_request.return_value.json.return_value = mock_response
        response = self.api.get_raw_measures(location_id=1, from_time='20240505T000000Z', to_time='20240505T235900Z')
        assert isinstance(response['data'], list)

    @patch('camp.apps.monitors.airgradient.api.requests.request')
    def test_calibrate_co2_by_location(self, mock_request):
        mock_response = {'status': 'calibration triggered'}
        mock_request.return_value.json.return_value = mock_response
        response = self.api.calibrate_co2_by_location(location_id=1)
        assert response['status'] == 'calibration triggered'

    @patch('camp.apps.monitors.airgradient.api.requests.request')
    def test_update_led_mode_by_serial(self, mock_request):
        mock_response = {'mode': 'pm'}
        mock_request.return_value.json.return_value = mock_response
        response = self.api.update_led_mode_by_serial(serialno='64e83301e678', mode='pm')
        assert response['mode'] == 'pm'
