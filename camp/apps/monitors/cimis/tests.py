from datetime import date, datetime, timedelta, timezone as dt_timezone
from unittest.mock import MagicMock, patch

import pytest

from django.conf import settings
from django.contrib.gis.geos import Point
from django.test import TestCase

from camp.apps.entries import models as entry_models
from camp.apps.monitors.cimis.api import CIMISAPI
from camp.apps.monitors.cimis.models import CIMIS
from camp.apps.monitors.cimis.tasks import parse_hms_coordinate, process_cimis_station
from camp.utils.datetime import localtime, make_aware


LA = settings.DEFAULT_TIMEZONE


def pacific(*args):
    return make_aware(datetime(*args), LA)


def cimis_record(date_str, hour_label, station='2', **fields):
    record = {'Date': date_str, 'Hour': hour_label, 'Station': station}
    record.update(fields or {'HlyAirTmp': {'Value': '50.0', 'Qc': ' ', 'Unit': '(F)'}})
    return record


def make_station(number='2'):
    return CIMIS.objects.create(
        name=f'Station {number}',
        station_number=number,
        position=Point(-119.7871, 36.7378, srid=4326),
        location=CIMIS.LOCATION.outside,
    )


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

    def test_session_header_has_subscription_key(self):
        assert self.api.session.headers['Ocp-Apim-Subscription-Key'] == 'test-key'

    @patch('camp.apps.monitors.cimis.api.requests.Session.get')
    def test_get_stations_returns_station_list(self, mock_get):
        mock_get.return_value = make_response(json_result={'Stations': [{'StationNbr': '2'}]})

        stations = self.api.get_stations()

        assert stations == [{'StationNbr': '2'}]
        called_url, called_kwargs = mock_get.call_args
        assert called_url[0] == 'https://et.water.ca.gov/StationWeb/GetAllStations'
        assert 'params' not in called_kwargs or not called_kwargs.get('params')
        assert self.api.session.headers['Ocp-Apim-Subscription-Key'] == 'test-key'

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
        assert called_url[0] == 'https://et.water.ca.gov/StationWeb/GetDataByStationNumber'
        params = called_kwargs['params']
        assert params['stationNbrs'] == '2,5'
        assert params['startDate'] == '2026-07-01'
        assert params['endDate'] == '2026-07-01'
        assert params['dataItems'] == 'hly-air-tmp,hly-wind-spd'
        assert params['unitOfMeasure'] == 'E'
        assert params['isHourly'] == 'true'
        assert 'appKey' not in params
        assert self.api.session.headers['Ocp-Apim-Subscription-Key'] == 'test-key'

    @patch('camp.apps.monitors.cimis.api.requests.Session.get')
    def test_get_hourly_data_converts_pascalcase_data_items_to_hyphenated_lowercase(self, mock_get):
        # Regression test: CIMIS.ENTRY_MAP.keys() -- what tasks.py actually
        # passes as data_items -- are PascalCase ('HlyAirTmp') to match the
        # response's field names. The live GetDataByStationNumber endpoint
        # rejects PascalCase in the dataItems query param (404 ERR1035);
        # it only accepts hyphenated lowercase ('hly-air-tmp'). Confirmed
        # live 2026-07-31.
        mock_get.return_value = make_response(json_result={
            'Data': {'Providers': []}
        })

        from datetime import date
        self.api.get_hourly_data(
            station_numbers=['2'],
            start_date=date(2026, 7, 1),
            end_date=date(2026, 7, 1),
            data_items=list(CIMIS.ENTRY_MAP.keys()),
        )

        called_kwargs = mock_get.call_args.kwargs
        assert called_kwargs['params']['dataItems'] == (
            'hly-air-tmp,hly-rel-hum,hly-dew-pnt,hly-soil-tmp,hly-wind-spd,'
            'hly-wind-dir,hly-precip,hly-sol-rad,hly-net-rad,hly-vap-pres,'
            'hly-asce-eto,hly-asce-etr'
        )


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
    fixtures = ['regions.yaml']

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

    def test_skips_station_missing_station_number(self):
        result = process_cimis_station.call_local(self.make_station(StationNbr=None))
        assert result is False


def utc(*args):
    return datetime(*args, tzinfo=dt_timezone.utc)


class CimisParseTimestampTests(TestCase):
    def setUp(self):
        self.monitor = CIMIS.objects.create(
            name='Station A',
            station_number='2',
            position=Point(-119.7871, 36.7378, srid=4326),
            location=CIMIS.LOCATION.outside,
        )

    def test_summer_label_is_the_start_of_the_hour_in_pst(self):
        # 0100 = 00:00-01:00 PST
        assert self.monitor.parse_timestamp({'Date': '2026-07-01', 'Hour': '0100'}) == utc(2026, 7, 1, 8)

    def test_winter_label_is_the_start_of_the_hour_in_pst(self):
        assert self.monitor.parse_timestamp({'Date': '2026-01-15', 'Hour': '1300'}) == utc(2026, 1, 15, 20)

    def test_2400_is_the_last_hour_of_the_same_date(self):
        assert self.monitor.parse_timestamp({'Date': '2026-07-01', 'Hour': '2400'}) == utc(2026, 7, 2, 7)

    def test_fall_back_day_has_24_distinct_hours(self):
        stamps = {self.monitor.parse_timestamp({'Date': '2026-11-01', 'Hour': f'{h:02d}00'}) for h in range(1, 25)}
        assert len(stamps) == 24
        assert min(stamps) == utc(2026, 11, 1, 8) and max(stamps) == utc(2026, 11, 2, 7)

    def test_spring_forward_day_has_24_distinct_hours(self):
        stamps = {self.monitor.parse_timestamp({'Date': '2026-03-08', 'Hour': f'{h:02d}00'}) for h in range(1, 25)}
        assert len(stamps) == 24

    def test_legacy_timestamp_matches_the_old_parsing(self):
        # end of hour, Pacific wall clock
        assert self.monitor.legacy_timestamp({'Date': '2026-07-01', 'Hour': '1300'}) == utc(2026, 7, 1, 20)
        assert self.monitor.legacy_timestamp({'Date': '2026-01-15', 'Hour': '2400'}) == utc(2026, 1, 16, 8)


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
        # 1300 on 2026-07-01 is the hour starting 12:00 PST (20:00 UTC)
        assert {e.timestamp for e in entries} == {utc(2026, 7, 1, 20)}

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

    def test_skips_a_value_too_large_for_its_column_and_keeps_the_rest(self):
        # A real reading from station 125, 2024-10-09 11:00.
        record = self.make_record(HlyVapPres={'Value': '8460.00', 'Qc': 'Q', 'Unit': '(mbar)'})
        entries = self.monitor.handle_payload(record)

        from camp.apps.entries import models as entry_models
        assert not entry_models.VaporPressure.objects.exists()
        assert any(isinstance(e, entry_models.Temperature) for e in entries)

    def test_skips_a_value_that_rounds_past_its_column(self):
        record = self.make_record(HlyVapPres={'Value': '99.996', 'Qc': ' ', 'Unit': '(mbar)'})
        self.monitor.handle_payload(record)

        from camp.apps.entries import models as entry_models
        assert not entry_models.VaporPressure.objects.exists()

    def test_skips_an_unparseable_value(self):
        record = self.make_record(HlyAirTmp={'Value': '--', 'Qc': ' ', 'Unit': '(F)'})
        entries = self.monitor.handle_payload(record)

        from camp.apps.entries import models as entry_models
        assert not any(isinstance(e, entry_models.Temperature) for e in entries)


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
        assert entries[0].timestamp == utc(2026, 7, 1, 20)

    def test_returns_false_for_unknown_station(self):
        from camp.apps.monitors.cimis.tasks import process_cimis_data

        record = {'Date': '2026-07-01', 'Hour': '1300', 'Station': '999'}
        result = process_cimis_data.call_local(record)

        assert result is False

    def test_returns_false_for_malformed_record_missing_date(self):
        from camp.apps.monitors.cimis.tasks import process_cimis_data

        record = {
            'Hour': '1300',
            'Station': '2',
            'HlyAirTmp': {'Value': '95.4', 'Qc': ' ', 'Unit': '(F)'},
        }
        result = process_cimis_data.call_local(record)

        assert result is False

    def test_uses_provided_monitor_without_database_lookup(self):
        from camp.apps.monitors.cimis.tasks import process_cimis_data

        # A monitor whose station_number doesn't match the record's 'Station'
        # proves the passed-in monitor is used directly, not re-derived from
        # the DB by looking up record['Station'].
        other_monitor = CIMIS.objects.create(
            name='Station B',
            station_number='999',
            position=Point(-119.0, 36.0, srid=4326),
            location=CIMIS.LOCATION.outside,
        )
        record = {
            'Date': '2026-07-01',
            'Hour': '1300',
            'Station': '2',
            'HlyAirTmp': {'Value': '95.4', 'Qc': ' ', 'Unit': '(F)'},
        }

        entries = process_cimis_data.call_local(record, monitor=other_monitor)

        assert entries is not False
        assert len(entries) == 1
        assert entries[0].monitor_id == other_monitor.pk


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

    @patch('camp.apps.monitors.cimis.tasks.CIMISAPI')
    def test_resolves_monitor_once_and_skips_database_lookup_per_record(self, MockAPI):
        monitor = CIMIS.objects.create(
            name='Station A',
            station_number='2',
            position=Point(-119.7871, 36.7378, srid=4326),
            location=CIMIS.LOCATION.outside,
        )
        record = {
            'Date': '2026-07-01',
            'Hour': '1300',
            'Station': '2',
            'HlyAirTmp': {'Value': '95.4', 'Qc': ' ', 'Unit': '(F)'},
        }
        mock_instance = MockAPI.return_value
        mock_instance.get_hourly_data.return_value = [{'Records': [record]}]

        from camp.apps.monitors.cimis.tasks import import_cimis_data
        with patch('camp.apps.monitors.cimis.models.CIMIS.objects.get') as mock_get:
            import_cimis_data()
            mock_get.assert_not_called()

        from camp.apps.entries import models as entry_models
        assert entry_models.Temperature.objects.filter(monitor=monitor).exists()

    @patch('camp.apps.monitors.cimis.tasks.CIMISAPI')
    def test_skips_record_for_unknown_station_without_querying(self, MockAPI):
        CIMIS.objects.create(
            name='Station A',
            station_number='2',
            position=Point(-119.7871, 36.7378, srid=4326),
            location=CIMIS.LOCATION.outside,
        )
        record = {
            'Date': '2026-07-01',
            'Hour': '1300',
            'Station': '999',
            'HlyAirTmp': {'Value': '95.4', 'Qc': ' ', 'Unit': '(F)'},
        }
        mock_instance = MockAPI.return_value
        mock_instance.get_hourly_data.return_value = [{'Records': [record]}]

        from camp.apps.monitors.cimis.tasks import import_cimis_data
        import_cimis_data()

        from camp.apps.entries import models as entry_models
        assert not entry_models.Temperature.objects.exists()

    @patch('camp.apps.monitors.cimis.tasks.CIMISAPI')
    def test_asks_for_the_pacific_date_after_the_utc_date_rolls_over(self, MockAPI):
        CIMIS.objects.create(
            name='Station A',
            station_number='2',
            position=Point(-119.7871, 36.7378, srid=4326),
            location=CIMIS.LOCATION.outside,
        )
        mock_instance = MockAPI.return_value
        mock_instance.get_hourly_data.return_value = []

        from camp.apps.monitors.cimis.tasks import import_cimis_data
        # 8:45 PM PDT on Oct 24 is already Oct 25 in UTC.
        with patch('django.utils.timezone.now', return_value=datetime(2026, 10, 25, 3, 45, tzinfo=dt_timezone.utc)):
            import_cimis_data()

        called_kwargs = mock_instance.get_hourly_data.call_args.kwargs
        assert called_kwargs['start_date'] == date(2026, 10, 24)
        assert called_kwargs['end_date'] == date(2026, 10, 24)

    @patch('camp.apps.monitors.cimis.tasks.CIMISAPI')
    def test_import_summarizes_the_hours_it_wrote(self, MockAPI):
        from camp.apps.monitors.cimis.tasks import import_cimis_data
        from camp.apps.summaries.models import BaseSummary, MonitorSummary, RegionSummary

        monitor = make_station()
        fields = {
            'HlyAirTmp': {'Value': '50.0', 'Qc': ' ', 'Unit': '(F)'},
            'HlyPrecip': {'Value': '0.01', 'Qc': ' ', 'Unit': '(in)'},
            'HlyWindDir': {'Value': '270', 'Qc': ' ', 'Unit': '(deg)'},
        }
        MockAPI.return_value.get_hourly_data.return_value = [{'Records': [
            cimis_record('2026-01-14', '1300', **fields),
            cimis_record('2026-01-14', '1400', **fields),
        ]}]

        with patch('django.utils.timezone.now', return_value=pacific(2026, 1, 14, 15, 45)):
            import_cimis_data()

        hourly = MonitorSummary.objects.filter(monitor=monitor, resolution=BaseSummary.Resolution.HOURLY)
        hours = {pacific(2026, 1, 14, 12), pacific(2026, 1, 14, 13)}
        for EntryModel in (entry_models.Temperature, entry_models.Precipitation):
            assert set(hourly.filter(entry_type=EntryModel.entry_type).values_list('timestamp', flat=True)) == hours
        assert not hourly.filter(entry_type=entry_models.WindDirection.entry_type).exists()
        # Today isn't over: nothing rolled yet, and never a region row.
        assert not MonitorSummary.objects.exclude(resolution=BaseSummary.Resolution.HOURLY).exists()
        assert not RegionSummary.objects.exists()

    @patch('camp.apps.monitors.cimis.tasks.CIMISAPI')
    def test_unchanged_reimport_enqueues_nothing(self, MockAPI):
        from camp.apps.monitors.cimis.tasks import import_cimis_data

        monitor = make_station()
        MockAPI.return_value.get_hourly_data.return_value = [{'Records': [
            cimis_record('2026-01-14', '1300'),
            cimis_record('2026-01-14', '1400'),
        ]}]

        with patch('django.utils.timezone.now', return_value=pacific(2026, 1, 14, 15, 45)), \
                patch('camp.apps.monitors.cimis.tasks.summarize_monitor_hours') as summarize:
            import_cimis_data()
            summarize.assert_called_once_with(
                str(monitor.pk), [pacific(2026, 1, 14, 12), pacific(2026, 1, 14, 13)],
            )
            summarize.reset_mock()

            import_cimis_data()
            summarize.assert_not_called()

    @patch('camp.apps.monitors.cimis.tasks.CIMISAPI')
    def test_a_record_with_only_wind_direction_enqueues_nothing(self, MockAPI):
        from camp.apps.monitors.cimis.tasks import import_cimis_data

        make_station()
        MockAPI.return_value.get_hourly_data.return_value = [{'Records': [
            cimis_record('2026-01-14', '1300', HlyWindDir={'Value': '270', 'Qc': ' ', 'Unit': '(deg)'}),
        ]}]

        with patch('django.utils.timezone.now', return_value=pacific(2026, 1, 14, 15, 45)), \
                patch('camp.apps.monitors.cimis.tasks.summarize_monitor_hours') as summarize:
            import_cimis_data()

        assert entry_models.WindDirection.objects.exists()
        summarize.assert_not_called()

    @patch('camp.apps.monitors.cimis.tasks.CIMISAPI')
    def test_late_reading_updates_an_already_rolled_day(self, MockAPI):
        from camp.apps.monitors.cimis.tasks import import_cimis_data
        from camp.apps.summaries.models import BaseSummary, MonitorSummary

        monitor = make_station()
        labels = [f'{h:02d}00' for h in range(1, 25)]
        missing = labels.pop(5)
        MockAPI.return_value.get_hourly_data.return_value = [{'Records': [
            cimis_record('2026-01-14', label) for label in labels
        ]}]
        with patch('django.utils.timezone.now', return_value=pacific(2026, 1, 15, 2, 45)):
            import_cimis_data()

        def daily():
            return MonitorSummary.objects.get(
                monitor=monitor, entry_type=entry_models.Temperature.entry_type,
                resolution=BaseSummary.Resolution.DAILY, timestamp=pacific(2026, 1, 14),
            )

        assert daily().count == 23

        MockAPI.return_value.get_hourly_data.return_value = [{'Records': [
            cimis_record('2026-01-14', missing),
        ]}]
        with patch('django.utils.timezone.now', return_value=pacific(2026, 1, 15, 3, 45)):
            import_cimis_data()

        assert daily().count == 24


class FinalizeCimisDataTests(TestCase):
    def test_no_op_when_no_monitors_exist(self):
        from camp.apps.monitors.cimis.tasks import finalize_cimis_data
        # Should not raise even with zero CIMIS monitors in the DB.
        finalize_cimis_data()

    @patch('camp.apps.monitors.cimis.tasks.CIMISAPI')
    def test_queries_yesterdays_full_day_for_all_known_stations(self, MockAPI):
        CIMIS.objects.create(
            name='Station A',
            station_number='2',
            position=Point(-119.7871, 36.7378, srid=4326),
            location=CIMIS.LOCATION.outside,
        )
        mock_instance = MockAPI.return_value
        mock_instance.get_hourly_data.return_value = []

        from camp.apps.monitors.cimis.tasks import finalize_cimis_data
        finalize_cimis_data()

        yesterday = localtime().date() - timedelta(days=1)
        called_kwargs = mock_instance.get_hourly_data.call_args.kwargs
        assert called_kwargs['station_numbers'] == ['2']
        assert called_kwargs['start_date'] == yesterday
        assert called_kwargs['end_date'] == yesterday
        assert sorted(called_kwargs['data_items']) == sorted(CIMIS.ENTRY_MAP.keys())

    @patch('camp.apps.monitors.cimis.tasks.CIMISAPI')
    def test_queries_the_pacific_yesterday(self, MockAPI):
        CIMIS.objects.create(
            name='Station A',
            station_number='2',
            position=Point(-119.7871, 36.7378, srid=4326),
            location=CIMIS.LOCATION.outside,
        )
        mock_instance = MockAPI.return_value
        mock_instance.get_hourly_data.return_value = []

        from camp.apps.monitors.cimis.tasks import finalize_cimis_data
        # Its 12:00 UTC run: 5 AM PDT on Oct 25.
        with patch('django.utils.timezone.now', return_value=datetime(2026, 10, 25, 12, 0, tzinfo=dt_timezone.utc)):
            finalize_cimis_data()

        called_kwargs = mock_instance.get_hourly_data.call_args.kwargs
        assert called_kwargs['start_date'] == date(2026, 10, 24)
        assert called_kwargs['end_date'] == date(2026, 10, 24)

    @patch('camp.apps.monitors.cimis.tasks.CIMISAPI')
    def test_ingests_records_from_yesterday(self, MockAPI):
        monitor = CIMIS.objects.create(
            name='Station A',
            station_number='2',
            position=Point(-119.7871, 36.7378, srid=4326),
            location=CIMIS.LOCATION.outside,
        )
        yesterday = localtime().date() - timedelta(days=1)
        record = {
            'Date': yesterday.strftime('%Y-%m-%d'),
            'Hour': '2400',
            'Station': '2',
            'HlyAirTmp': {'Value': '88.1', 'Qc': ' ', 'Unit': '(F)'},
        }
        mock_instance = MockAPI.return_value
        mock_instance.get_hourly_data.return_value = [{'Records': [record]}]

        from camp.apps.monitors.cimis.tasks import finalize_cimis_data
        finalize_cimis_data()

        from camp.apps.entries import models as entry_models
        entries = entry_models.Temperature.objects.filter(monitor=monitor)
        assert entries.count() == 1
        # 2400 is the hour starting 23:00 PST on the record's date
        pst_day = datetime.strptime(record['Date'], '%Y-%m-%d')
        assert entries.get().timestamp == utc(pst_day.year, pst_day.month, pst_day.day, 7) + timedelta(days=1)

    @patch('camp.apps.monitors.cimis.tasks.CIMISAPI')
    def test_rerun_applies_a_qc_revised_value(self, MockAPI):
        # This is the whole point of finalize_cimis_data: re-pulling
        # yesterday after CIMIS's QC window closes should actually apply
        # a value CIMIS revised, not silently discard it as a duplicate.
        monitor = CIMIS.objects.create(
            name='Station A',
            station_number='2',
            position=Point(-119.7871, 36.7378, srid=4326),
            location=CIMIS.LOCATION.outside,
        )
        yesterday = localtime().date() - timedelta(days=1)

        def record(value):
            return {
                'Date': yesterday.strftime('%Y-%m-%d'),
                'Hour': '2400',
                'Station': '2',
                'HlyAirTmp': {'Value': value, 'Qc': ' ', 'Unit': '(F)'},
            }

        mock_instance = MockAPI.return_value
        mock_instance.get_hourly_data.return_value = [{'Records': [record('88.1')]}]

        from camp.apps.monitors.cimis.tasks import finalize_cimis_data
        finalize_cimis_data()

        from camp.apps.entries import models as entry_models
        entries = entry_models.Temperature.objects.filter(monitor=monitor)
        original_value = entries.get().value

        mock_instance.get_hourly_data.return_value = [{'Records': [record('91.4')]}]
        finalize_cimis_data()

        entries = entry_models.Temperature.objects.filter(monitor=monitor)
        assert entries.count() == 1
        assert entries.get().value != original_value

    @patch('camp.apps.monitors.cimis.tasks.CIMISAPI')
    def test_finalize_resummarizes_all_of_yesterday_for_every_station(self, MockAPI):
        from camp.apps.monitors.cimis.tasks import finalize_cimis_data
        from camp.apps.summaries.models import BaseSummary, MonitorSummary, RegionSummary
        from camp.apps.summaries.periods import iter_hours

        stations = [make_station('2'), make_station('5')]
        # Readings already stored (an earlier import wrote them), never summarized.
        for monitor in stations:
            for hour in (0, 11, 23):
                entry_models.Temperature.objects.create(
                    monitor=monitor, timestamp=pacific(2026, 1, 14, hour),
                    stage=entry_models.Temperature.Stage.RAW, processor='',
                    value=50, location=monitor.location,
                )
        MockAPI.return_value.get_hourly_data.return_value = []

        # Its 12:00 UTC run: 4 AM PST on Jan 15.
        now = pacific(2026, 1, 15, 4)
        with patch('django.utils.timezone.now', return_value=now), \
                patch('camp.apps.monitors.cimis.tasks.summarize_monitor_hours') as summarize:
            finalize_cimis_data()
        yesterday = list(iter_hours(pacific(2026, 1, 14), pacific(2026, 1, 15)))
        assert summarize.call_count == 2
        assert {c.args[0]: c.args[1] for c in summarize.call_args_list} == {
            str(monitor.pk): yesterday for monitor in stations
        }

        with patch('django.utils.timezone.now', return_value=now):
            finalize_cimis_data()
        for monitor in stations:
            rows = MonitorSummary.objects.filter(monitor=monitor, entry_type=entry_models.Temperature.entry_type)
            assert rows.filter(resolution=BaseSummary.Resolution.HOURLY).count() == 3
            assert rows.get(resolution=BaseSummary.Resolution.DAILY, timestamp=pacific(2026, 1, 14)).count == 3
        assert not RegionSummary.objects.exists()

    @patch('camp.apps.monitors.cimis.tasks.CIMISAPI')
    def test_finalize_also_summarizes_changed_hours_past_the_pacific_day(self, MockAPI):
        from camp.apps.monitors.cimis.tasks import finalize_cimis_data
        from camp.apps.summaries.periods import iter_hours

        monitor = make_station()
        # In summer, 2400 PST on Jul 14 is 00:00 PDT on Jul 15.
        MockAPI.return_value.get_hourly_data.return_value = [{'Records': [
            cimis_record('2026-07-14', '2400'),
        ]}]
        with patch('django.utils.timezone.now', return_value=pacific(2026, 7, 15, 5)), \
                patch('camp.apps.monitors.cimis.tasks.summarize_monitor_hours') as summarize:
            finalize_cimis_data()

        yesterday = list(iter_hours(pacific(2026, 7, 14), pacific(2026, 7, 15)))
        summarize.assert_called_once_with(str(monitor.pk), yesterday + [pacific(2026, 7, 15, 0)])


class ImportCimisHistoryTests(TestCase):
    def test_no_op_when_no_monitors_exist(self):
        from django.core.management import call_command
        from io import StringIO

        out = StringIO()
        call_command('import_cimis_history', start='2026-07-01', end='2026-07-02', stdout=out)

        assert 'discover_cimis_stations' in out.getvalue()

    def test_invalid_date_raises_command_error(self):
        from django.core.management import call_command, CommandError

        with pytest.raises(CommandError):
            call_command('import_cimis_history', start='not-a-date', end='2026-07-02')

    def test_start_after_end_raises_command_error(self):
        from django.core.management import call_command, CommandError

        with pytest.raises(CommandError):
            call_command('import_cimis_history', start='2026-07-05', end='2026-07-01')

    @patch('camp.apps.monitors.cimis.tasks.CIMISAPI')
    def test_ingests_one_day_at_a_time_across_the_range(self, MockAPI):
        from django.core.management import call_command

        CIMIS.objects.create(
            name='Station A',
            station_number='2',
            position=Point(-119.7871, 36.7378, srid=4326),
            location=CIMIS.LOCATION.outside,
        )
        mock_instance = MockAPI.return_value
        mock_instance.get_hourly_data.return_value = []

        call_command('import_cimis_history', start='2026-07-01', end='2026-07-03')

        called_days = [
            (call.kwargs['start_date'], call.kwargs['end_date'])
            for call in mock_instance.get_hourly_data.call_args_list
        ]
        assert called_days == [
            (date(2026, 7, 1), date(2026, 7, 1)),
            (date(2026, 7, 2), date(2026, 7, 2)),
            (date(2026, 7, 3), date(2026, 7, 3)),
        ]

    @patch('camp.apps.monitors.cimis.tasks.CIMISAPI')
    def test_ingests_records_across_the_range(self, MockAPI):
        from django.core.management import call_command

        monitor = CIMIS.objects.create(
            name='Station A',
            station_number='2',
            position=Point(-119.7871, 36.7378, srid=4326),
            location=CIMIS.LOCATION.outside,
        )
        record = {
            'Date': '2026-07-01',
            'Hour': '1300',
            'Station': '2',
            'HlyAirTmp': {'Value': '95.4', 'Qc': ' ', 'Unit': '(F)'},
        }
        mock_instance = MockAPI.return_value
        mock_instance.get_hourly_data.return_value = [{'Records': [record]}]

        call_command('import_cimis_history', start='2026-07-01', end='2026-07-01')

        assert entry_models.Temperature.objects.filter(monitor=monitor).exists()
