import csv
import io
import tempfile
from datetime import date, datetime, timezone
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.core.management import call_command

from django.contrib.gis.geos import Point
from django.test import TestCase

from camp.apps.calibrations import processors as cal_processors
from camp.apps.entries import models as entry_models
from camp.apps.monitors.vozbox.api import VozBoxClient
from camp.apps.monitors.vozbox.models import VOZBox
from camp.apps.monitors.vozbox.tasks import process_device


DAILY_CSV = """\
"","objectId","event","unixtime","m_PM1_CF1","m_PM1_ATM","m_PM1_b","m_PM25_CF1","m_PM25_ATM","m_PM25_b","m_PM4_b","m_PM10_CF1","m_PM10_ATM","m_PM10_b","n_PM03_P","n_PM05_P","n_PM05_b","n_PM1_P","n_PM1_b","n_PM25_P","n_PM25_b","n_PM4_b","tempC_pms","rh_pms","n_PM10_b","typ_size_b","temp_C","tempC_sen5x","rh","rh_sen5x","o3","vocIdx","noxIdx","lat","lon","alt","sats","counter","moos","ver","coreid","published_at","createdAt","updatedAt","date"
"1","abc","MOOSPMv3Parser",1749427200,7,7,4,10,10,4,4,10,10,4,1598,443,22378,54,30,2,30,30,34,20,30,0,36,39,26,25,70.0,74,1,36.785328,-119.773125,72.5,5,600,58,3,"e00fce68f12da1a0c5de6248",2025-06-09 00:00:02,2025-06-09 00:00:03,2025-06-09 00:00:03,2025-06-09
"2","def","MOOSPMv3Parser",1749427200,6,6,3,9,9,3,3,9,9,3,1573,396,25264,57,32,3,32,32,34,18,32,0,35,38,27,24,65.0,55,1,36.785351,-119.773140,74.9,7,600,58,3,"e00fce68e88237db75a60608",2025-06-09 00:00:02,2025-06-09 00:00:03,2025-06-09 00:00:03,2025-06-09
"""

CAL_CSV = """\
unixtime,m_PM25_CF1,m_PM25_ATM,m_PM25_b,m_PM10_CF1,m_PM10_ATM,m_PM10_b,temp_C,rh,o3,lat,lon,coreid,C1_T,C2_rh,C3_o3,b,o3_cal
1750428000,5,5,4,6,6,4,16,54,26.981,36.785343,-119.773056,e00fce682bbf742cd0b6768a,0.594,−0.117,0.426,8.44,23.127
1750428000,0,0,4,1,1,4,16,53,0.0,36.785404,-119.773109,e00fce68b74b750aa2a7da46,,,,,-999.0
"""


class VozBoxClientParseTests(TestCase):
    def _write_csv(self, content):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.csv', delete=False, encoding='utf-8') as f:
            f.write(content)
            return Path(f.name)

    def test_parse_daily_csv_groups_by_coreid(self):
        with VozBoxClient() as client:
            path = self._write_csv(DAILY_CSV)
            result = client.parse_csv(path)

        assert 'e00fce68f12da1a0c5de6248' in result
        assert 'e00fce68e88237db75a60608' in result
        assert len(result) == 2

    def test_parse_daily_csv_normalizes_row(self):
        with VozBoxClient() as client:
            path = self._write_csv(DAILY_CSV)
            result = client.parse_csv(path)

        row = result['e00fce68f12da1a0c5de6248'][0]
        assert row['timestamp'] == datetime(2025, 6, 9, 0, 0, 0, tzinfo=timezone.utc)
        assert row['pm1_a'] == 7.0
        assert row['pm1_b'] == 4.0
        assert row['pm25_a'] == 10.0
        assert row['pm25_b'] == 4.0
        assert row['pm10_a'] == 10.0
        assert row['pm10_b'] == 4.0
        assert row['temperature'] == 36.0
        assert row['humidity'] == 26.0
        assert row['o3'] == 70.0
        assert row['latitude'] == 36.785328
        assert row['longitude'] == -119.773125

    def test_parse_cal_csv_includes_o3_cal(self):
        with VozBoxClient() as client:
            path = self._write_csv(CAL_CSV)
            result = client.parse_csv(path)

        row = result['e00fce682bbf742cd0b6768a'][0]
        assert row['o3_cal'] == 23.127
        assert row['pm25_a'] == 5.0
        assert row['pm1_a'] is None   # cal CSV has no m_PM1_ATM column

    def test_parse_cal_csv_returns_none_o3_cal_for_invalid_row(self):
        with VozBoxClient() as client:
            path = self._write_csv(CAL_CSV)
            result = client.parse_csv(path)

        row = result['e00fce68b74b750aa2a7da46'][0]
        assert row['o3_cal'] == -999.0  # value exists but calibration invalid (handled by consumer)

    def test_parse_csv_skips_rows_without_coreid(self):
        content = (
            'unixtime,m_PM25_ATM,m_PM25_b,coreid\n'
            '1749427200,10,4,\n'
            '1749427200,10,4,e00fce68f12da1a0c5de6248\n'
        )
        with VozBoxClient() as client:
            path = self._write_csv(content)
            result = client.parse_csv(path)

        assert len(result) == 1

    def test_parse_csv_skips_rows_with_invalid_unixtime(self):
        content = (
            'unixtime,m_PM25_ATM,m_PM25_b,coreid\n'
            'notanumber,10,4,e00fce68f12da1a0c5de6248\n'
        )
        with VozBoxClient() as client:
            path = self._write_csv(content)
            result = client.parse_csv(path)

        assert result == {}


class VozBoxClientHTTPTests(TestCase):
    def _make_response(self, status_code=200, text=''):
        resp = MagicMock()
        resp.status_code = status_code
        resp.text = text
        resp.json.return_value = []
        resp.raise_for_status = MagicMock()
        return resp

    @patch('camp.apps.monitors.vozbox.api.requests.Session')
    def test_get_daily_data_returns_none_on_404(self, MockSession):
        MockSession.return_value.__enter__ = lambda s: s
        MockSession.return_value.get.return_value = self._make_response(404)

        with VozBoxClient() as client:
            result = client.get_daily_data(date(2025, 6, 9))

        assert result is None

    @patch('camp.apps.monitors.vozbox.api.requests.Session')
    def test_get_daily_data_parses_csv_on_200(self, MockSession):
        MockSession.return_value.__enter__ = lambda s: s
        MockSession.return_value.get.return_value = self._make_response(200, text=DAILY_CSV)

        with VozBoxClient() as client:
            result = client.get_daily_data(date(2025, 6, 9))

        assert result is not None
        assert 'e00fce68f12da1a0c5de6248' in result

    @patch('camp.apps.monitors.vozbox.api.requests.Session')
    def test_list_daily_files_returns_sorted_dates(self, MockSession):
        api_response = MagicMock()
        api_response.status_code = 200
        api_response.raise_for_status = MagicMock()
        api_response.json.return_value = [
            {'name': 'moospmV3_2025-06-09.csv'},
            {'name': 'moospmV3_2025-06-08.csv'},
            {'name': '.RData'},
            {'name': 'carb_data_cleaning.Rout'},
        ]
        MockSession.return_value.__enter__ = lambda s: s
        MockSession.return_value.get.return_value = api_response

        with VozBoxClient() as client:
            result = client.list_daily_files()

        assert result == [date(2025, 6, 8), date(2025, 6, 9)]

    @patch('camp.apps.monitors.vozbox.api.requests.Session')
    def test_list_cal_files_returns_sorted_date_hour_tuples(self, MockSession):
        api_response = MagicMock()
        api_response.status_code = 200
        api_response.raise_for_status = MagicMock()
        api_response.json.return_value = [
            {'name': 'moospmV3_cal_2025-06-20T15.csv'},
            {'name': 'moospmV3_cal_2025-06-20T14.csv'},
        ]
        MockSession.return_value.__enter__ = lambda s: s
        MockSession.return_value.get.return_value = api_response

        with VozBoxClient() as client:
            result = client.list_cal_files()

        assert result == [(date(2025, 6, 20), 14), (date(2025, 6, 20), 15)]

    @patch('camp.apps.monitors.vozbox.api.requests.Session')
    def test_context_manager_cleans_up_tmpdir(self, MockSession):
        with VozBoxClient() as client:
            tmpdir_name = client._tmpdir.name
            assert Path(tmpdir_name).exists()
        assert not Path(tmpdir_name).exists()


class VOZBoxModelTests(TestCase):
    def _make_row(self, **kwargs):
        defaults = {
            'timestamp': datetime(2025, 6, 9, 0, 0, 0, tzinfo=timezone.utc),
            'pm1_a': 7.0, 'pm1_b': 4.0,
            'pm25_a': 10.0, 'pm25_b': 4.0,
            'pm10_a': 10.0, 'pm10_b': 4.0,
            'temperature': 36.0,
            'humidity': 26.0,
            'o3': 70.0,
            'o3_cal': None,
            'latitude': 36.785328,
            'longitude': -119.773125,
        }
        defaults.update(kwargs)
        return defaults

    def test_update_data_sets_position(self):
        monitor = VOZBox(sensor_id='e00fce68f12da1a0c5de6248')
        monitor.update_data(self._make_row())
        assert monitor.position.coords == Point(-119.773125, 36.785328).coords

    def test_update_data_sets_name_from_coreid_when_empty(self):
        monitor = VOZBox(sensor_id='e00fce68f12da1a0c5de6248')
        monitor.update_data(self._make_row())
        assert monitor.name == 'e00fce68f12da1a0c5de6248'

    def test_update_data_does_not_overwrite_existing_name(self):
        monitor = VOZBox(sensor_id='e00fce68f12da1a0c5de6248', name='Coalinga')
        monitor.update_data(self._make_row())
        assert monitor.name == 'Coalinga'

    def test_update_data_sets_location_outside(self):
        monitor = VOZBox(sensor_id='e00fce68f12da1a0c5de6248')
        monitor.update_data(self._make_row())
        assert monitor.location == 'outside'

    def test_supports_health_checks(self):
        monitor = VOZBox(sensor_id='e00fce68f12da1a0c5de6248')
        assert monitor.supports_health_checks() is True

    def test_create_entries_produces_all_types(self):
        monitor = VOZBox.objects.create(
            sensor_id='e00fce68f12da1a0c5de6248',
            name='Test',
            location='outside',
        )
        row = self._make_row()
        entries = monitor.create_entries(row)
        entry_types = {type(e) for e in entries}
        assert entry_models.PM10 in entry_types    # PM1.0
        assert entry_models.PM25 in entry_types
        assert entry_models.PM100 in entry_types
        assert entry_models.Temperature in entry_types
        assert entry_models.Humidity in entry_types
        assert entry_models.O3 in entry_types

    def test_create_entries_dual_channel_pm25(self):
        monitor = VOZBox.objects.create(
            sensor_id='e00fce68f12da1a0c5de6248',
            name='Test',
            location='outside',
        )
        row = self._make_row()
        entries = monitor.create_entries(row)
        pm25_entries = [e for e in entries if isinstance(e, entry_models.PM25)]
        sensors = {e.sensor for e in pm25_entries}
        assert sensors == {'a', 'b'}

    def test_create_entries_skips_none_values(self):
        monitor = VOZBox.objects.create(
            sensor_id='e00fce68f12da1a0c5de6248',
            name='Test',
            location='outside',
        )
        row = self._make_row(pm25_a=None)
        entries = monitor.create_entries(row)
        pm25_a_entries = [e for e in entries if isinstance(e, entry_models.PM25) and e.sensor == 'a']
        assert pm25_a_entries == []


class ProcessDeviceTests(TestCase):
    def _make_rows(self, coreid, count=2):
        rows = []
        for i in range(count):
            rows.append({
                'timestamp': datetime(2025, 6, 9, i, 0, 0, tzinfo=timezone.utc),
                'pm1_a': 7.0, 'pm1_b': 4.0,
                'pm25_a': 10.0, 'pm25_b': 4.0,
                'pm10_a': 10.0, 'pm10_b': 4.0,
                'temperature': 36.0,
                'humidity': 26.0,
                'o3': 70.0,
                'o3_cal': None,
                'latitude': 36.785328,
                'longitude': -119.773125,
            })
        return rows

    def test_process_device_creates_monitor_on_first_encounter(self):
        coreid = 'e00fce68f12da1a0c5de6248'
        rows = self._make_rows(coreid)
        process_device(coreid, rows)
        assert VOZBox.objects.filter(sensor_id=coreid).exists()

    def test_process_device_uses_existing_monitor(self):
        coreid = 'e00fce68f12da1a0c5de6248'
        monitor = VOZBox.objects.create(
            sensor_id=coreid,
            name='Coalinga',
            location='outside',
        )
        rows = self._make_rows(coreid)
        process_device(coreid, rows)
        assert VOZBox.objects.filter(sensor_id=coreid).count() == 1
        monitor.refresh_from_db()
        assert monitor.name == 'Coalinga'

    def test_process_device_creates_entries(self):
        coreid = 'e00fce68f12da1a0c5de6248'
        rows = self._make_rows(coreid, count=1)
        process_device(coreid, rows)
        monitor = VOZBox.objects.get(sensor_id=coreid)
        assert entry_models.PM25.objects.filter(monitor=monitor).exists()
        assert entry_models.O3.objects.filter(monitor=monitor).exists()

    def test_process_device_deduplicates_rows(self):
        coreid = 'e00fce68f12da1a0c5de6248'
        rows = self._make_rows(coreid, count=1)
        process_device(coreid, rows)
        process_device(coreid, rows)   # second call with same rows
        monitor = VOZBox.objects.get(sensor_id=coreid)
        pm25_count = entry_models.PM25.objects.filter(monitor=monitor, sensor='a', stage='raw').count()
        assert pm25_count == 1   # no duplicates

    def test_process_device_skips_rows_before_latest(self):
        coreid = 'e00fce68f12da1a0c5de6248'
        rows = self._make_rows(coreid, count=3)
        process_device(coreid, rows[:2])   # process first 2
        process_device(coreid, rows)        # process all 3 (first 2 already exist)
        monitor = VOZBox.objects.get(sensor_id=coreid)
        pm25_count = entry_models.PM25.objects.filter(monitor=monitor, sensor='a', stage='raw').count()
        assert pm25_count == 3


class O3VOZBoxProcessorTests(TestCase):
    def test_processor_is_registered(self):
        assert 'O3_VOZBox' in cal_processors

    def test_processor_name(self):
        assert cal_processors.O3_VOZBox.name == 'O3_VOZBox'

    def test_processor_entry_model_is_o3(self):
        assert cal_processors.O3_VOZBox.entry_model == entry_models.O3

    def test_processor_required_stage_is_raw(self):
        assert cal_processors.O3_VOZBox.required_stage == entry_models.O3.Stage.RAW

    def test_processor_next_stage_is_calibrated(self):
        assert cal_processors.O3_VOZBox.next_stage == entry_models.O3.Stage.CALIBRATED

    def test_processor_returns_none_when_no_calibration(self):
        monitor = VOZBox.objects.create(
            sensor_id='e00fce68test0001',
            name='Test O3',
            location='outside',
        )
        o3_entry = entry_models.O3.objects.create(
            monitor=monitor,
            location='outside',
            sensor='1',
            stage=entry_models.O3.Stage.RAW,
            value=25.0,
        )
        result = cal_processors.O3_VOZBox(o3_entry).run()
        assert result is None


class ImportVozboxCalTests(TestCase):
    def setUp(self):
        self.monitor = VOZBox.objects.create(
            sensor_id='e00fce682bbf742cd0b6768a',
            name='Lost Hills',
            location='outside',
        )

    def _cal_rows(self):
        return {
            'e00fce682bbf742cd0b6768a': [{
                'timestamp': datetime(2025, 6, 20, 15, 0, 0, tzinfo=timezone.utc),
                'pm25_a': 5.0, 'pm25_b': 4.0,
                'pm10_a': 6.0, 'pm10_b': 4.0,
                'pm1_a': None, 'pm1_b': None,
                'temperature': 16.0,
                'humidity': 54.0,
                'o3': 26.981,
                'o3_cal': 23.127,
                'latitude': 36.785343,
                'longitude': -119.773056,
            }],
        }

    @patch('camp.apps.monitors.vozbox.management.commands.import_vozbox_cal.VozBoxClient')
    def test_creates_calibrated_o3_entry(self, MockClient):
        instance = MockClient.return_value.__enter__.return_value
        instance.list_cal_files.return_value = [(date(2025, 6, 20), 15)]
        instance.get_cal_data.return_value = self._cal_rows()

        out = StringIO()
        call_command('import_vozbox_cal', stdout=out)

        assert entry_models.O3.objects.filter(
            monitor=self.monitor,
            stage=entry_models.O3.Stage.CALIBRATED,
            sensor='1',
        ).exists()

    @patch('camp.apps.monitors.vozbox.management.commands.import_vozbox_cal.VozBoxClient')
    def test_skips_unknown_coreids(self, MockClient):
        rows = self._cal_rows()
        rows['unknown_coreid_xyz'] = rows['e00fce682bbf742cd0b6768a']
        instance = MockClient.return_value.__enter__.return_value
        instance.list_cal_files.return_value = [(date(2025, 6, 20), 15)]
        instance.get_cal_data.return_value = rows

        out = StringIO()
        call_command('import_vozbox_cal', stdout=out)

        assert 'unknown_coreid_xyz' in out.getvalue()

    @patch('camp.apps.monitors.vozbox.management.commands.import_vozbox_cal.VozBoxClient')
    def test_date_range_filter(self, MockClient):
        instance = MockClient.return_value.__enter__.return_value
        instance.list_cal_files.return_value = [
            (date(2025, 6, 19), 12),
            (date(2025, 6, 20), 15),
            (date(2025, 6, 21), 8),
        ]
        instance.get_cal_data.return_value = {}

        call_command('import_vozbox_cal', start='2025-06-20', end='2025-06-20')

        assert instance.get_cal_data.call_count == 1
        instance.get_cal_data.assert_called_once_with(date(2025, 6, 20), 15)

    @patch('camp.apps.monitors.vozbox.management.commands.import_vozbox_cal.VozBoxClient')
    def test_skips_row_when_o3_cal_is_negative(self, MockClient):
        rows = self._cal_rows()
        rows['e00fce682bbf742cd0b6768a'][0]['o3_cal'] = -999.0
        instance = MockClient.return_value.__enter__.return_value
        instance.list_cal_files.return_value = [(date(2025, 6, 20), 15)]
        instance.get_cal_data.return_value = rows

        call_command('import_vozbox_cal')

        assert not entry_models.O3.objects.filter(
            monitor=self.monitor,
            stage=entry_models.O3.Stage.CALIBRATED,
        ).exists()

    @patch('camp.apps.monitors.vozbox.management.commands.import_vozbox_cal.VozBoxClient')
    def test_skips_row_when_o3_cal_is_none(self, MockClient):
        rows = self._cal_rows()
        rows['e00fce682bbf742cd0b6768a'][0]['o3_cal'] = None
        instance = MockClient.return_value.__enter__.return_value
        instance.list_cal_files.return_value = [(date(2025, 6, 20), 15)]
        instance.get_cal_data.return_value = rows

        call_command('import_vozbox_cal')

        assert not entry_models.O3.objects.filter(
            monitor=self.monitor,
            stage=entry_models.O3.Stage.CALIBRATED,
        ).exists()
