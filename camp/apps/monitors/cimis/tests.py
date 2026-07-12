from unittest.mock import MagicMock, patch

from django.contrib.gis.geos import Point
from django.test import TestCase

from camp.apps.entries import models as entry_models
from camp.apps.monitors.cimis.api import CIMISAPI
from camp.apps.monitors.cimis.models import CIMIS
from camp.apps.monitors.cimis.tasks import parse_hms_coordinate, process_cimis_station


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


class ParseHmsCoordinateTests(TestCase):
    def test_parses_valid_latitude(self):
        assert parse_hms_coordinate("36º20'10N / 36.3360") == 36.3360

    def test_parses_valid_negative_longitude(self):
        assert parse_hms_coordinate("-120º6'47W / -120.1130") == -120.1130

    def test_returns_none_for_missing_slash(self):
        assert parse_hms_coordinate('garbage') is None

    def test_returns_none_for_empty_string(self):
        assert parse_hms_coordinate('') is None


class ProcessCimisStationTests(TestCase):
    def make_station(self, **overrides):
        station = {
            'StationNbr': '2',
            'Name': 'Five Points',
            'County': 'Fresno',
            'IsActive': 'True',
            'HmsLatitude': "36º20'10N / 36.3360",
            'HmsLongitude': "-120º6'47W / -120.1130",
        }
        station.update(overrides)
        return station

    def test_creates_monitor_for_active_sjv_county_station(self):
        monitor = process_cimis_station.call_local(self.make_station())

        assert monitor is not False
        assert monitor.station_number == '2'
        assert monitor.county == 'Fresno'

    def test_skips_station_outside_sjv_counties(self):
        result = process_cimis_station.call_local(self.make_station(County='Los Angeles'))
        assert result is False

    def test_skips_inactive_station(self):
        result = process_cimis_station.call_local(self.make_station(IsActive='False'))
        assert result is False

    def test_skips_station_with_unparseable_coordinates(self):
        result = process_cimis_station.call_local(self.make_station(HmsLatitude='garbage'))
        assert result is False

    def test_is_idempotent_for_existing_station(self):
        process_cimis_station.call_local(self.make_station())
        result = process_cimis_station.call_local(self.make_station(Name='Five Points Updated'))

        from camp.apps.monitors.cimis.models import CIMIS
        assert CIMIS.objects.filter(station_number='2').count() == 1
        assert result is not False


from datetime import datetime


class CimisParseTimestampTests(TestCase):
    def setUp(self):
        self.monitor = CIMIS.objects.create(
            name='Station A',
            station_number='2',
            position=Point(-119.7871, 36.7378, srid=4326),
            location=CIMIS.LOCATION.outside,
        )

    def test_parses_normal_hour(self):
        timestamp = self.monitor.parse_timestamp({'Date': '2026-07-01', 'Hour': '0100'})
        local = timestamp.astimezone(timestamp.tzinfo)
        assert (local.year, local.month, local.day, local.hour, local.minute) == (2026, 7, 1, 1, 0)

    def test_parses_midnight_boundary_hour_2400(self):
        timestamp = self.monitor.parse_timestamp({'Date': '2026-07-01', 'Hour': '2400'})
        local = timestamp.astimezone(timestamp.tzinfo)
        assert (local.year, local.month, local.day, local.hour, local.minute) == (2026, 7, 2, 0, 0)


class CimisHandlePayloadTests(TestCase):
    def setUp(self):
        self.monitor = CIMIS.objects.create(
            name='Station A',
            station_number='2',
            position=Point(-119.7871, 36.7378, srid=4326),
            location=CIMIS.LOCATION.outside,
        )

    def make_record(self, **overrides):
        record = {
            'Date': '2026-07-01',
            'Hour': '1300',
            'Station': '2',
            'HlyAirTmp': {'Value': '95.4', 'Qc': ' ', 'Unit': '(F)'},
            'HlyRelHum': {'Value': '22.0', 'Qc': ' ', 'Unit': '(%)'},
            'HlyWindSpd': {'Value': '5.1', 'Qc': 'R', 'Unit': '(mph)'},
            'HlyAsceEto': {'Value': None, 'Qc': 'N', 'Unit': '(in)'},
        }
        record.update(overrides)
        return record

    def test_creates_entries_for_present_qc_acceptable_fields(self):
        entries = self.monitor.handle_payload(self.make_record())
        entry_types = {type(e) for e in entries}

        from camp.apps.entries import models as entry_models
        assert entry_models.Temperature in entry_types
        assert entry_models.Humidity in entry_types

    def test_ingests_estimated_qc_flagged_values(self):
        entries = self.monitor.handle_payload(self.make_record())

        from decimal import Decimal
        from camp.apps.entries import models as entry_models
        wind_entries = [e for e in entries if isinstance(e, entry_models.WindSpeed)]
        assert len(wind_entries) == 1
        assert wind_entries[0].value == Decimal('5.1')

    def test_skips_field_flagged_not_available(self):
        entries = self.monitor.handle_payload(self.make_record())

        from camp.apps.entries import models as entry_models
        assert not any(isinstance(e, entry_models.ETo) for e in entries)

    def test_skips_field_missing_from_record(self):
        record = self.make_record()
        del record['HlyRelHum']
        entries = self.monitor.handle_payload(record)

        from camp.apps.entries import models as entry_models
        assert not any(isinstance(e, entry_models.Humidity) for e in entries)


class ProcessCimisDataTests(TestCase):
    def setUp(self):
        self.monitor = CIMIS.objects.create(
            name='Station A',
            station_number='2',
            position=Point(-119.7871, 36.7378, srid=4326),
            location=CIMIS.LOCATION.outside,
        )

    def test_creates_entries_for_known_station(self):
        from camp.apps.monitors.cimis.tasks import process_cimis_data

        record = {
            'Date': '2026-07-01',
            'Hour': '1300',
            'Station': '2',
            'HlyAirTmp': {'Value': '95.4', 'Qc': ' ', 'Unit': '(F)'},
        }
        entries = process_cimis_data.call_local(record)

        assert entries is not False
        assert len(entries) == 1

    def test_returns_false_for_unknown_station(self):
        from camp.apps.monitors.cimis.tasks import process_cimis_data

        record = {'Date': '2026-07-01', 'Hour': '1300', 'Station': '999'}
        result = process_cimis_data.call_local(record)

        assert result is False


class ImportCimisDataTests(TestCase):
    def test_no_op_when_no_monitors_exist(self):
        from camp.apps.monitors.cimis.tasks import import_cimis_data
        # Should not raise even with zero CIMIS monitors in the DB.
        import_cimis_data()

    @patch('camp.apps.monitors.cimis.tasks.CIMISAPI')
    def test_calls_api_with_all_known_station_numbers(self, MockAPI):
        CIMIS.objects.create(
            name='Station A',
            station_number='2',
            position=Point(-119.7871, 36.7378, srid=4326),
            location=CIMIS.LOCATION.outside,
        )
        CIMIS.objects.create(
            name='Station B',
            station_number='5',
            position=Point(-119.0, 36.0, srid=4326),
            location=CIMIS.LOCATION.outside,
        )
        mock_instance = MockAPI.return_value
        mock_instance.get_hourly_data.return_value = []

        from camp.apps.monitors.cimis.tasks import import_cimis_data
        import_cimis_data()

        called_kwargs = mock_instance.get_hourly_data.call_args.kwargs
        assert sorted(called_kwargs['station_numbers']) == ['2', '5']
        assert sorted(called_kwargs['data_items']) == sorted(CIMIS.ENTRY_MAP.keys())
