from django.test import TestCase
from unittest.mock import patch

from camp.apps.monitors.airgradient.api import AirGradientAPI
from camp.apps.monitors.airgradient.models import AirGradient
from camp.apps.monitors.models import Monitor


class HealthCheckSupportTests(TestCase):
    _next_sensor_id = 1

    def make_monitor(self, device):
        sensor_id = HealthCheckSupportTests._next_sensor_id
        HealthCheckSupportTests._next_sensor_id += 1
        return AirGradient.objects.create(name=f'Test {device}', device=device, sensor_id=sensor_id)

    def test_dual_channel_supports_health_checks(self):
        monitor = self.make_monitor('O-1PP')
        assert monitor.supports_health_checks() is True

    def test_single_channel_does_not_support_health_checks(self):
        monitor = self.make_monitor('O-1PST')
        assert monitor.supports_health_checks() is False

    def test_health_check_queryset_filter_includes_device(self):
        f = AirGradient.health_check_queryset_filter()
        assert f.get('airgradient__isnull') is False
        assert f.get('airgradient__device') == 'O-1PP'

    def test_get_for_health_checks_includes_dual_channel(self):
        self.make_monitor('O-1PP')
        assert Monitor.objects.get_for_health_checks().count() == 1

    def test_get_for_health_checks_excludes_single_channel(self):
        self.make_monitor('O-1PST')
        assert Monitor.objects.get_for_health_checks().count() == 0


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
