from unittest.mock import MagicMock, patch

from django.contrib.gis.geos import Point
from django.test import TestCase

from camp.apps.entries import models as entry_models
from camp.apps.monitors.cimis.api import CIMISAPI
from camp.apps.monitors.cimis.models import CIMIS


class CIMISModelTests(TestCase):
    def test_entry_config_maps_all_twelve_fields(self):
        assert len(CIMIS.ENTRY_CONFIG) == 12
        assert CIMIS.ENTRY_MAP['HlyAirTmp'] is entry_models.Temperature
        assert CIMIS.ENTRY_MAP['HlyAsceEto'] is entry_models.ETo

    def test_station_number_is_unique(self):
        CIMIS.objects.create(
            name='Station A',
            station_number='2',
            position=Point(-119.7871, 36.7378, srid=4326),
            location=CIMIS.LOCATION.outside,
        )
        with self.assertRaises(Exception):
            CIMIS.objects.create(
                name='Station B',
                station_number='2',
                position=Point(-119.0, 36.0, srid=4326),
                location=CIMIS.LOCATION.outside,
            )

    def test_supports_health_checks_is_false(self):
        monitor = CIMIS.objects.create(
            name='Station A',
            station_number='2',
            position=Point(-119.7871, 36.7378, srid=4326),
            location=CIMIS.LOCATION.outside,
        )
        assert monitor.supports_health_checks() is False


def make_response(status_code=200, json_result=None):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = json_result
    response.raise_for_status = MagicMock()
    if status_code >= 400:
        response.raise_for_status.side_effect = Exception(f'HTTP {status_code}')
    return response


class CIMISAPITests(TestCase):
    def setUp(self):
        self.api = CIMISAPI(app_key='test-key')

    @patch('camp.apps.monitors.cimis.api.requests.Session.get')
    def test_get_stations_returns_station_list(self, mock_get):
        mock_get.return_value = make_response(json_result={'Stations': [{'StationNbr': '2'}]})

        stations = self.api.get_stations()

        assert stations == [{'StationNbr': '2'}]
        called_url, called_kwargs = mock_get.call_args
        assert called_url[0] == 'https://et.water.ca.gov/api/station'
        assert called_kwargs['params']['appKey'] == 'test-key'

    @patch('camp.apps.monitors.cimis.api.requests.Session.get')
    def test_get_hourly_data_builds_correct_params(self, mock_get):
        mock_get.return_value = make_response(json_result={
            'Data': {'Providers': [{'Name': 'cimis', 'Records': []}]}
        })

        from datetime import date
        providers = self.api.get_hourly_data(
            station_numbers=['2', '5'],
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 1),
            data_items=['hly-air-tmp', 'hly-wind-spd'],
        )

        assert providers == [{'Name': 'cimis', 'Records': []}]
        called_url, called_kwargs = mock_get.call_args
        assert called_url[0] == 'https://et.water.ca.gov/api/data'
        params = called_kwargs['params']
        assert params['targets'] == '2,5'
        assert params['startDate'] == '2026-07-01'
        assert params['endDate'] == '2026-07-01'
        assert params['dataItems'] == 'hly-air-tmp,hly-wind-spd'
        assert params['unitOfMeasure'] == 'E'
        assert params['appKey'] == 'test-key'
