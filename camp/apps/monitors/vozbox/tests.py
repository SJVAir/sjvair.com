import csv
import io
import tempfile
from datetime import date, datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from django.core.management import call_command, CommandError

from django.contrib.gis.geos import Point
from django.db.models import Count as models_Count
from django.test import TestCase
from django.utils import timezone as django_timezone

from camp.apps.calibrations import processors as cal_processors
from camp.apps.entries import models as entry_models
from camp.apps.monitors.vozbox.api import VozBoxClient
from camp.apps.monitors.models import LatestEntry, Monitor
from camp.apps.monitors.vozbox.models import VOZBox
from camp.apps.monitors.vozbox.tasks import process_device, import_realtime, import_cal_range, _bin_rows


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
        assert row['pm1_plantower'] == 7.0
        assert row['pm1_sensirion'] == 4.0
        assert row['pm25_plantower'] == 10.0
        assert row['pm25_sensirion'] == 4.0
        assert row['pm10_plantower'] == 10.0
        assert row['pm10_sensirion'] == 4.0
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
        assert row['pm25_plantower'] == 5.0
        assert row['pm1_plantower'] is None   # cal CSV has no m_PM1_ATM column

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

    def test_normalize_row_drops_pm_values_over_9999(self):
        content = (
            'unixtime,m_PM1_ATM,m_PM1_b,m_PM25_ATM,m_PM25_b,m_PM10_ATM,m_PM10_b,temp_C,rh,o3,lat,lon,coreid\n'
            '1749427200,10000,12000,12196,4,12807,4,36,26,70,36.79,-119.77,e00fce68f12da1a0c5de6248\n'
        )
        with VozBoxClient() as client:
            path = self._write_csv(content)
            result = client.parse_csv(path)

        row = result['e00fce68f12da1a0c5de6248'][0]
        assert row['pm1_plantower'] is None    # 10000 > 9999
        assert row['pm1_sensirion'] is None    # 12000 > 9999
        assert row['pm25_plantower'] is None   # 12196 > 9999
        assert row['pm10_plantower'] is None   # 12807 > 9999
        assert row['pm25_sensirion'] == 4.0    # valid value unchanged
        assert row['pm10_sensirion'] == 4.0    # valid value unchanged


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

    def _mock_tree_response(self, filenames, truncated=False):
        # Listing a folder is a single git-trees request for the folder's
        # `<branch>:<path>` subtree -- see VozBoxClient._list_folder_filenames().
        response = MagicMock()
        response.raise_for_status = MagicMock()
        response.json.return_value = {
            'truncated': truncated,
            'tree': [{'path': name, 'type': 'blob'} for name in filenames],
        }
        return response

    @patch('camp.apps.monitors.vozbox.api.requests.Session')
    def test_list_daily_files_returns_sorted_dates(self, MockSession):
        MockSession.return_value.__enter__ = lambda s: s
        MockSession.return_value.get.return_value = self._mock_tree_response([
            'moospmV3_2025-06-09.csv',
            'moospmV3_2025-06-08.csv',
            '.RData',
            'carb_data_cleaning.Rout',
        ])

        with VozBoxClient() as client:
            result = client.list_daily_files()

        url = MockSession.return_value.get.call_args[0][0]
        assert url.endswith('/git/trees/main:moospmV3_daily')

        assert result == [date(2025, 6, 8), date(2025, 6, 9)]

    @patch('camp.apps.monitors.vozbox.api.requests.Session')
    def test_list_cal_files_returns_sorted_date_hour_tuples(self, MockSession):
        MockSession.return_value.__enter__ = lambda s: s
        MockSession.return_value.get.return_value = self._mock_tree_response([
            'moospmV3_cal_2025-06-20T15.csv',
            'moospmV3_cal_2025-06-20T14.csv',
        ])

        with VozBoxClient() as client:
            result = client.list_cal_files()

        assert result == [(date(2025, 6, 20), 14), (date(2025, 6, 20), 15)]

    @patch('camp.apps.monitors.vozbox.api.requests.Session')
    def test_list_daily_files_raises_when_folder_tree_truncated(self, MockSession):
        MockSession.return_value.__enter__ = lambda s: s
        MockSession.return_value.get.return_value = self._mock_tree_response(
            ['moospmV3_2025-06-09.csv'], truncated=True,
        )

        with VozBoxClient() as client:
            with pytest.raises(RuntimeError):
                client.list_daily_files()

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
            'pm1_plantower': 7.0, 'pm1_sensirion': 4.0,
            'pm25_plantower': 10.0, 'pm25_sensirion': 4.0,
            'pm10_plantower': 10.0, 'pm10_sensirion': 4.0,
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

    def test_does_not_support_health_checks(self):
        # Plantower + Sensirion, not a matched A/B pair.
        monitor = VOZBox(sensor_id='e00fce68f12da1a0c5de6248')
        assert monitor.supports_health_checks() is False

    def test_health_checks_not_enabled_for_type(self):
        assert VOZBox.health_checks_enabled() is False

    def test_get_for_health_checks_excludes_vozbox(self):
        # Two PM2.5 sensors are listed in ENTRY_CONFIG, but they are not a
        # matched pair, so the hourly task must not pick these monitors up.
        VOZBox.objects.create(sensor_id='e00fce68f12da1a0c5de6248', name='Coalinga', location='outside')
        assert Monitor.objects.get_for_health_checks().count() == 0

    def test_pm25_is_raw_only(self):
        config = VOZBox.ENTRY_CONFIG[entry_models.PM25]
        assert config['allowed_stages'] == [entry_models.PM25.Stage.RAW]
        assert config['default_stage'] == entry_models.PM25.Stage.RAW
        assert 'processors' not in config
        assert 'alerts' not in config

    def test_process_device_stores_both_pm25_sensors_raw_only(self):
        monitor = VOZBox.objects.create(sensor_id='e00fce68f12da1a0c5de6248', name='Test', location='outside')
        for entry in monitor.create_entries(self._make_row()):
            monitor.process_entry_pipeline(entry)
        pm25 = entry_models.PM25.objects.filter(monitor=monitor)
        assert set(pm25.values_list('stage', flat=True)) == {entry_models.PM25.Stage.RAW}
        assert set(pm25.values_list('sensor', flat=True)) == {'plantower', 'sensirion'}

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
        assert sensors == {'plantower', 'sensirion'}

    def test_create_entries_skips_none_values(self):
        monitor = VOZBox.objects.create(
            sensor_id='e00fce68f12da1a0c5de6248',
            name='Test',
            location='outside',
        )
        row = self._make_row(pm25_plantower=None)
        entries = monitor.create_entries(row)
        pm25_plantower_entries = [e for e in entries if isinstance(e, entry_models.PM25) and e.sensor == 'plantower']
        assert pm25_plantower_entries == []


class ProcessDeviceTests(TestCase):
    def _make_rows(self, coreid, count=2):
        rows = []
        for i in range(count):
            rows.append({
                'timestamp': datetime(2025, 6, 9, i, 0, 0, tzinfo=timezone.utc),
                'pm1_plantower': 7.0, 'pm1_sensirion': 4.0,
                'pm25_plantower': 10.0, 'pm25_sensirion': 4.0,
                'pm10_plantower': 10.0, 'pm10_sensirion': 4.0,
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
        pm25_count = entry_models.PM25.objects.filter(monitor=monitor, sensor='plantower', stage='raw').count()
        assert pm25_count == 1   # no duplicates

    def test_process_device_skips_rows_before_latest(self):
        coreid = 'e00fce68f12da1a0c5de6248'
        rows = self._make_rows(coreid, count=3)
        process_device(coreid, rows[:2])   # process first 2
        process_device(coreid, rows)        # process all 3 (first 2 already exist)
        monitor = VOZBox.objects.get(sensor_id=coreid)
        pm25_count = entry_models.PM25.objects.filter(monitor=monitor, sensor='plantower', stage='raw').count()
        assert pm25_count == 3

    def test_process_device_cutoff_ignores_sensor_names(self):
        # Legacy rows are named 'a'/'b' until cleanup_vozbox_pm runs.
        # The cutoff must still see them, or the fetch window gets re-created
        # under the new names (the unique constraint includes sensor, so it
        # wouldn't stop that).
        coreid = 'e00fce68f12da1a0c5de6248'
        rows = self._make_rows(coreid, count=3)
        process_device(coreid, rows[:2])
        monitor = VOZBox.objects.get(sensor_id=coreid)
        for EntryModel in (entry_models.PM10, entry_models.PM25, entry_models.PM100):
            EntryModel.objects.filter(monitor=monitor, sensor='plantower').update(sensor='a')
            EntryModel.objects.filter(monitor=monitor, sensor='sensirion').update(sensor='b')

        process_device(coreid, rows)

        pm25 = entry_models.PM25.objects.filter(monitor=monitor, stage='raw')
        assert pm25.count() == 6   # 3 timestamps x 2 sensors, no duplicates
        assert pm25.filter(timestamp=rows[2]['timestamp']).count() == 2

    def test_process_device_creates_calibrated_o3_when_o3_cal_present(self):
        coreid = 'e00fce68f12da1a0c5de6248'
        rows = self._make_rows(coreid, count=1)
        rows[0]['o3_cal'] = 23.127
        process_device(coreid, rows)
        monitor = VOZBox.objects.get(sensor_id=coreid)
        calibrated = entry_models.O3.objects.filter(monitor=monitor, stage=entry_models.O3.Stage.CALIBRATED)
        assert calibrated.count() == 1
        assert calibrated.first().processor == 'VOZBox_QuinnCal'

    def test_process_device_calibrated_o3_becomes_latest_entry(self):
        # End-to-end check of the DefaultCalibration wiring: a named
        # processor matching the DefaultCalibration('vozbox', 'o3') row
        # is required for update_latest_entry to actually treat this as
        # the displayed value instead of silently discarding it.
        coreid = 'e00fce68f12da1a0c5de6248'
        rows = self._make_rows(coreid, count=1)
        rows[0]['o3_cal'] = 23.127
        process_device(coreid, rows)
        monitor = VOZBox.objects.get(sensor_id=coreid)

        from camp.apps.monitors.models import LatestEntry
        latest = LatestEntry.objects.get(
            monitor=monitor,
            entry_type=entry_models.O3.entry_type,
            processor='VOZBox_QuinnCal',
        )
        assert latest.entry.stage == entry_models.O3.Stage.CALIBRATED

    def test_process_device_skips_calibrated_o3_when_o3_cal_missing(self):
        coreid = 'e00fce68f12da1a0c5de6248'
        rows = self._make_rows(coreid, count=1)   # o3_cal is None by default
        process_device(coreid, rows)
        monitor = VOZBox.objects.get(sensor_id=coreid)
        assert not entry_models.O3.objects.filter(monitor=monitor, stage=entry_models.O3.Stage.CALIBRATED).exists()

    def test_process_device_skips_calibrated_o3_when_o3_cal_negative(self):
        coreid = 'e00fce68f12da1a0c5de6248'
        rows = self._make_rows(coreid, count=1)
        rows[0]['o3_cal'] = -999.0   # sentinel for invalid calibration
        process_device(coreid, rows)
        monitor = VOZBox.objects.get(sensor_id=coreid)
        assert not entry_models.O3.objects.filter(monitor=monitor, stage=entry_models.O3.Stage.CALIBRATED).exists()


class ImportRealtimeTests(TestCase):
    """
    Regression coverage: import_realtime must pull from the hourly
    moospmV3_cal feed (get_cal_data), not moospmV3_daily
    (get_daily_data) -- the daily rollup only gets written once a day
    and can lag a full day behind. moospmV3_cal was confirmed to carry
    every row/field moospmV3 has (same commit, same timestamps) plus
    o3_cal, so it's a strict superset -- no need for a separate
    moospmV3-only fetch.
    """

    @patch('camp.apps.monitors.vozbox.tasks.process_device')
    @patch('camp.apps.monitors.vozbox.tasks.VozBoxClient')
    def test_queries_current_and_previous_hour(self, MockClient, mock_process_device):
        client_instance = MockClient.return_value.__enter__.return_value
        client_instance.get_cal_data.return_value = None

        import_realtime.call_local()

        now = django_timezone.now()
        current_hour = now.replace(minute=0, second=0, microsecond=0)
        previous_hour = current_hour - timedelta(hours=1)

        called_args = [call.args for call in client_instance.get_cal_data.call_args_list]
        assert (previous_hour.date(), previous_hour.hour) in called_args
        assert (current_hour.date(), current_hour.hour) in called_args
        assert client_instance.get_daily_data.call_count == 0

    @patch('camp.apps.monitors.vozbox.tasks.process_device')
    @patch('camp.apps.monitors.vozbox.tasks.VozBoxClient')
    def test_schedules_process_device_per_coreid(self, MockClient, mock_process_device):
        ts = datetime(2026, 8, 3, 15, 0, tzinfo=timezone.utc)
        client_instance = MockClient.return_value.__enter__.return_value
        client_instance.get_cal_data.side_effect = [
            {'coreid-a': [{'timestamp': ts}]},
            {'coreid-a': [{'timestamp': ts}], 'coreid-b': [{'timestamp': ts}]},
        ]

        import_realtime.call_local()

        scheduled_coreids = {call.args[0][0] for call in mock_process_device.schedule.call_args_list}
        assert scheduled_coreids == {'coreid-a', 'coreid-b'}


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


class VOZBoxQuinnCalTests(TestCase):
    def test_processor_is_registered(self):
        assert 'VOZBox_QuinnCal' in cal_processors

    def test_processor_name(self):
        assert cal_processors.VOZBox_QuinnCal.name == 'VOZBox_QuinnCal'

    def test_processor_entry_model_is_o3(self):
        assert cal_processors.VOZBox_QuinnCal.entry_model == entry_models.O3

    def test_processor_next_stage_is_calibrated(self):
        assert cal_processors.VOZBox_QuinnCal.next_stage == entry_models.O3.Stage.CALIBRATED

    def test_is_the_default_calibration_for_vozbox_o3(self):
        from camp.apps.calibrations.utils import get_default_calibration
        assert get_default_calibration(VOZBox, entry_models.O3) == 'VOZBox_QuinnCal'


class BinRowsTests(TestCase):
    def _row(self, ts):
        return {'timestamp': ts, 'pm25_plantower': 10.0}

    def test_keeps_one_row_per_10min_bucket(self):
        rows = [
            self._row(datetime(2026, 7, 10, 12, 0, 0, tzinfo=timezone.utc)),
            self._row(datetime(2026, 7, 10, 12, 0, 30, tzinfo=timezone.utc)),
            self._row(datetime(2026, 7, 10, 12, 1, 0, tzinfo=timezone.utc)),
        ]
        result = _bin_rows(rows)
        assert len(result) == 1
        assert result[0]['timestamp'] == datetime(2026, 7, 10, 12, 0, 0, tzinfo=timezone.utc)

    def test_keeps_earliest_row_in_bucket(self):
        rows = [
            self._row(datetime(2026, 7, 10, 12, 3, 0, tzinfo=timezone.utc)),
            self._row(datetime(2026, 7, 10, 12, 1, 0, tzinfo=timezone.utc)),
            self._row(datetime(2026, 7, 10, 12, 7, 0, tzinfo=timezone.utc)),
        ]
        result = _bin_rows(rows)
        assert len(result) == 1
        assert result[0]['timestamp'] == datetime(2026, 7, 10, 12, 1, 0, tzinfo=timezone.utc)

    def test_separate_buckets_for_different_10min_windows(self):
        rows = [
            self._row(datetime(2026, 7, 10, 12, 0, 0, tzinfo=timezone.utc)),
            self._row(datetime(2026, 7, 10, 12, 5, 0, tzinfo=timezone.utc)),
            self._row(datetime(2026, 7, 10, 12, 10, 0, tzinfo=timezone.utc)),
            self._row(datetime(2026, 7, 10, 12, 15, 0, tzinfo=timezone.utc)),
        ]
        result = _bin_rows(rows)
        assert len(result) == 2
        assert result[0]['timestamp'] == datetime(2026, 7, 10, 12, 0, 0, tzinfo=timezone.utc)
        assert result[1]['timestamp'] == datetime(2026, 7, 10, 12, 10, 0, tzinfo=timezone.utc)

    def test_10min_device_rows_unchanged(self):
        rows = [
            self._row(datetime(2026, 7, 10, 12, 0, 0, tzinfo=timezone.utc)),
            self._row(datetime(2026, 7, 10, 12, 10, 0, tzinfo=timezone.utc)),
            self._row(datetime(2026, 7, 10, 12, 20, 0, tzinfo=timezone.utc)),
        ]
        result = _bin_rows(rows)
        assert len(result) == 3

    def test_empty_rows_returns_empty(self):
        assert _bin_rows([]) == []


class ImportCalRangeTests(TestCase):
    """
    import_vozbox_cal was removed -- import_vozbox_history now covers
    both raw and calibrated data in one idempotent pass. These test the
    shared import_cal_range() function directly instead of a command.
    """

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
                'pm25_plantower': 5.0, 'pm25_sensirion': 4.0,
                'pm10_plantower': 6.0, 'pm10_sensirion': 4.0,
                'pm1_plantower': None, 'pm1_sensirion': None,
                'temperature': 16.0,
                'humidity': 54.0,
                'o3': 26.981,
                'o3_cal': 23.127,
                'latitude': 36.785343,
                'longitude': -119.773056,
            }],
        }

    def test_creates_calibrated_o3_entry(self):
        client = MagicMock()
        client.list_cal_files.return_value = [(date(2025, 6, 20), 15)]
        client.get_cal_data.return_value = self._cal_rows()

        import_cal_range(client)

        entry = entry_models.O3.objects.get(
            monitor=self.monitor,
            stage=entry_models.O3.Stage.CALIBRATED,
            sensor='1',
        )
        assert entry.processor == 'VOZBox_QuinnCal'

    def test_skips_unknown_coreids(self):
        rows = self._cal_rows()
        rows['unknown_coreid_xyz'] = rows['e00fce682bbf742cd0b6768a']
        client = MagicMock()
        client.list_cal_files.return_value = [(date(2025, 6, 20), 15)]
        client.get_cal_data.return_value = rows

        messages = []
        import_cal_range(client, log=messages.append)

        assert any('unknown_coreid_xyz' in m for m in messages)

    def test_date_range_filter(self):
        client = MagicMock()
        client.list_cal_files.return_value = [
            (date(2025, 6, 19), 12),
            (date(2025, 6, 20), 15),
            (date(2025, 6, 21), 8),
        ]
        client.get_cal_data.return_value = {}

        import_cal_range(client, start=date(2025, 6, 20), end=date(2025, 6, 20))

        assert client.get_cal_data.call_count == 1
        client.get_cal_data.assert_called_once_with(date(2025, 6, 20), 15)

    def test_skips_row_when_o3_cal_is_negative(self):
        rows = self._cal_rows()
        rows['e00fce682bbf742cd0b6768a'][0]['o3_cal'] = -999.0
        client = MagicMock()
        client.list_cal_files.return_value = [(date(2025, 6, 20), 15)]
        client.get_cal_data.return_value = rows

        import_cal_range(client)

        assert not entry_models.O3.objects.filter(
            monitor=self.monitor,
            stage=entry_models.O3.Stage.CALIBRATED,
        ).exists()

    def test_skips_row_when_o3_cal_is_none(self):
        rows = self._cal_rows()
        rows['e00fce682bbf742cd0b6768a'][0]['o3_cal'] = None
        client = MagicMock()
        client.list_cal_files.return_value = [(date(2025, 6, 20), 15)]
        client.get_cal_data.return_value = rows

        import_cal_range(client)

        assert not entry_models.O3.objects.filter(
            monitor=self.monitor,
            stage=entry_models.O3.Stage.CALIBRATED,
        ).exists()

    def test_rerun_updates_changed_value(self):
        client = MagicMock()
        client.list_cal_files.return_value = [(date(2025, 6, 20), 15)]
        client.get_cal_data.return_value = self._cal_rows()
        import_cal_range(client)

        updated_rows = self._cal_rows()
        updated_rows['e00fce682bbf742cd0b6768a'][0]['o3_cal'] = 30.0
        client.get_cal_data.return_value = updated_rows
        import_cal_range(client)

        entries = entry_models.O3.objects.filter(
            monitor=self.monitor,
            stage=entry_models.O3.Stage.CALIBRATED,
        )
        assert entries.count() == 1
        assert round(entries.first().value, 1) == 30.0


class ImportVozboxHistoryTests(TestCase):
    def _daily_rows(self, coreid='e00fce68f12da1a0c5de6248', timestamp=None):
        return {
            coreid: [{
                'timestamp': timestamp or datetime(2025, 6, 9, 0, 0, 0, tzinfo=timezone.utc),
                'pm1_plantower': 7.0, 'pm1_sensirion': 4.0,
                'pm25_plantower': 10.0, 'pm25_sensirion': 4.0,
                'pm10_plantower': 10.0, 'pm10_sensirion': 4.0,
                'temperature': 36.0,
                'humidity': 26.0,
                'o3': 70.0,
                'o3_cal': None,
                'latitude': 36.785328,
                'longitude': -119.773125,
            }],
        }

    @patch('camp.apps.monitors.vozbox.management.commands.import_vozbox_history.VozBoxClient')
    def test_creates_monitor_and_entries(self, MockClient):
        coreid = 'e00fce68f12da1a0c5de6248'
        instance = MockClient.return_value.__enter__.return_value
        instance.list_daily_files.return_value = [date(2025, 6, 9)]
        instance.get_daily_data.return_value = self._daily_rows(coreid)

        call_command('import_vozbox_history')

        monitor = VOZBox.objects.get(sensor_id=coreid)
        assert entry_models.PM25.objects.filter(monitor=monitor, sensor='plantower', stage='raw').exists()
        assert entry_models.O3.objects.filter(monitor=monitor, sensor='1', stage='raw').exists()

    @patch('camp.apps.monitors.vozbox.management.commands.import_vozbox_history.VozBoxClient')
    def test_date_range_filter(self, MockClient):
        instance = MockClient.return_value.__enter__.return_value
        instance.list_daily_files.return_value = [
            date(2025, 6, 8),
            date(2025, 6, 9),
            date(2025, 6, 10),
        ]
        instance.get_daily_data.return_value = {}

        call_command('import_vozbox_history', start='2025-06-09', end='2025-06-09')

        instance.get_daily_data.assert_called_once_with(date(2025, 6, 9))

    @patch('camp.apps.monitors.vozbox.management.commands.import_vozbox_history.VozBoxClient')
    def test_skips_day_with_no_data(self, MockClient):
        instance = MockClient.return_value.__enter__.return_value
        instance.list_daily_files.return_value = [date(2025, 6, 9)]
        instance.get_daily_data.return_value = None

        call_command('import_vozbox_history')

        assert VOZBox.objects.count() == 0

    @patch('camp.apps.monitors.vozbox.management.commands.import_vozbox_history.VozBoxClient')
    def test_rerun_does_not_duplicate_entries(self, MockClient):
        coreid = 'e00fce68f12da1a0c5de6248'
        instance = MockClient.return_value.__enter__.return_value
        instance.list_daily_files.return_value = [date(2025, 6, 9)]
        instance.get_daily_data.return_value = self._daily_rows(coreid)

        call_command('import_vozbox_history')
        call_command('import_vozbox_history')

        monitor = VOZBox.objects.get(sensor_id=coreid)
        pm25_count = entry_models.PM25.objects.filter(monitor=monitor, sensor='plantower', stage='raw').count()
        assert pm25_count == 1

    @patch('camp.apps.monitors.vozbox.management.commands.import_vozbox_history.VozBoxClient')
    def test_rerun_updates_changed_raw_value(self, MockClient):
        coreid = 'e00fce68f12da1a0c5de6248'
        instance = MockClient.return_value.__enter__.return_value
        instance.list_daily_files.return_value = [date(2025, 6, 9)]
        instance.get_daily_data.return_value = self._daily_rows(coreid)

        call_command('import_vozbox_history')

        updated_rows = self._daily_rows(coreid)
        updated_rows[coreid][0]['pm25_plantower'] = 99.0
        instance.get_daily_data.return_value = updated_rows

        call_command('import_vozbox_history')

        monitor = VOZBox.objects.get(sensor_id=coreid)
        entries = entry_models.PM25.objects.filter(monitor=monitor, sensor='plantower', stage='raw')
        assert entries.count() == 1
        assert round(entries.first().value, 1) == 99.0

    @patch('camp.apps.monitors.vozbox.management.commands.import_vozbox_history.VozBoxClient')
    def test_invalid_date_raises_command_error(self, MockClient):
        with pytest.raises(CommandError):
            call_command('import_vozbox_history', start='not-a-date')

    @patch('camp.apps.monitors.vozbox.management.commands.import_vozbox_history.VozBoxClient')
    def test_also_backfills_calibrated_o3(self, MockClient):
        coreid = 'e00fce68f12da1a0c5de6248'
        instance = MockClient.return_value.__enter__.return_value
        instance.list_daily_files.return_value = [date(2025, 6, 9)]
        instance.get_daily_data.return_value = self._daily_rows(coreid)
        instance.list_cal_files.return_value = [(date(2025, 6, 9), 0)]
        instance.get_cal_data.return_value = {
            coreid: [{
                'timestamp': datetime(2025, 6, 9, 0, 0, 0, tzinfo=timezone.utc),
                'o3_cal': 23.127,
            }],
        }

        call_command('import_vozbox_history')

        monitor = VOZBox.objects.get(sensor_id=coreid)
        entry = entry_models.O3.objects.get(monitor=monitor, stage=entry_models.O3.Stage.CALIBRATED)
        assert entry.processor == 'VOZBox_QuinnCal'

    @patch('camp.apps.monitors.vozbox.management.commands.import_vozbox_history.VozBoxClient')
    def test_calibrated_o3_backfill_respects_date_range(self, MockClient):
        instance = MockClient.return_value.__enter__.return_value
        instance.list_daily_files.return_value = []
        instance.list_cal_files.return_value = [
            (date(2025, 6, 8), 0),
            (date(2025, 6, 9), 0),
            (date(2025, 6, 10), 0),
        ]
        instance.get_cal_data.return_value = {}

        call_command('import_vozbox_history', start='2025-06-09', end='2025-06-09')

        instance.get_cal_data.assert_called_once_with(date(2025, 6, 9), 0)


class CleanupVozboxPmCommandTests(TestCase):
    def setUp(self):
        self.monitor = VOZBox.objects.create(sensor_id='e00fce68rename', name='Rename', location='outside')
        base = datetime(2025, 6, 9, 0, 0, tzinfo=timezone.utc)
        for i in range(7):
            ts = base + timedelta(minutes=10 * i)
            for EntryModel in (entry_models.PM10, entry_models.PM25, entry_models.PM100):
                EntryModel.objects.create(monitor=self.monitor, timestamp=ts, sensor='a', stage='raw', value=1)
                EntryModel.objects.create(monitor=self.monitor, timestamp=ts, sensor='b', stage='raw', value=2)
        # Another monitor type's rows named 'a' must be untouched.
        from camp.apps.monitors.purpleair.models import PurpleAir
        self.other = PurpleAir.objects.create(name='PA', sensor_id=424242, location='outside')
        entry_models.PM25.objects.create(monitor=self.other, timestamp=base, sensor='a', stage='raw', value=3)

    def _sensors(self, EntryModel, monitor):
        return dict(EntryModel.objects.filter(monitor=monitor).values_list('sensor').annotate(n=models_Count('id')))

    def test_renames_in_batches_with_progress(self):
        out = StringIO()
        call_command('cleanup_vozbox_pm', batch_size=3, stdout=out)
        for EntryModel in (entry_models.PM10, entry_models.PM25, entry_models.PM100):
            assert self._sensors(EntryModel, self.monitor) == {'plantower': 7, 'sensirion': 7}
        assert self._sensors(entry_models.PM25, self.other) == {'a': 1}
        text = out.getvalue()
        assert "e00fce68rename pm25 'a'->'plantower': 7 renamed, 0 duplicates removed" in text
        assert 'Renamed 42 rows, removed 0 legacy rows' in text

    def test_legacy_row_with_existing_renamed_twin_is_deleted(self):
        # A reading already stored under the new name (e.g. re-imported by
        # new code before the rename ran) would collide on unique_entry_*
        # if the legacy copy were renamed -- drop the legacy copy instead.
        ts = datetime(2025, 6, 9, 0, 0, tzinfo=timezone.utc)
        entry_models.PM25.objects.create(monitor=self.monitor, timestamp=ts, sensor='plantower', stage='raw', value=1)
        out = StringIO()
        call_command('cleanup_vozbox_pm', batch_size=3, stdout=out)
        pm25 = entry_models.PM25.objects.filter(monitor=self.monitor)
        assert dict(pm25.values_list('sensor').annotate(n=models_Count('id'))) == {'plantower': 7, 'sensirion': 7}
        assert pm25.filter(timestamp=ts, sensor='plantower').count() == 1
        assert "pm25 'a'->'plantower': 6 renamed, 1 duplicates removed" in out.getvalue()

    def test_idempotent(self):
        call_command('cleanup_vozbox_pm', stdout=StringIO())
        out = StringIO()
        call_command('cleanup_vozbox_pm', stdout=out)
        assert 'nothing to do' in out.getvalue()
        assert 'Renamed 0 rows, removed 0 legacy rows' in out.getvalue()

    def test_dry_run_writes_nothing(self):
        out = StringIO()
        call_command('cleanup_vozbox_pm', dry_run=True, stdout=out)
        assert self._sensors(entry_models.PM25, self.monitor) == {'a': 7, 'b': 7}
        assert 'Would rename 42 rows, removed 0 legacy rows' in out.getvalue()

    def test_removes_legacy_pm25_stages_latest_entries_and_health_checks(self):
        from camp.apps.monitors.models import LatestEntry
        from camp.apps.qaqc.models import HealthCheck
        PM25 = entry_models.PM25
        ts = datetime(2025, 6, 9, 0, 0, tzinfo=timezone.utc)
        for stage in (PM25.Stage.CORRECTED, PM25.Stage.CLEANED, PM25.Stage.CALIBRATED):
            legacy = PM25.objects.create(monitor=self.monitor, timestamp=ts, sensor='', stage=stage, processor='X', value=1)
        raw = PM25.objects.filter(monitor=self.monitor, sensor='a').first()
        LatestEntry.objects.create(monitor=self.monitor, entry_type='pm25', stage=PM25.Stage.CLEANED, processor='X', entry_id=legacy.pk, timestamp=ts)
        raw_latest = LatestEntry.objects.create(monitor=self.monitor, entry_type='pm25', stage=PM25.Stage.RAW, processor='', entry_id=raw.pk, timestamp=ts)
        hc = HealthCheck.objects.create(monitor=self.monitor, hour=ts, score=1)
        self.monitor.health = hc
        self.monitor.save()
        # Another type's health checks are untouched.
        other_hc = HealthCheck.objects.create(monitor=self.other, hour=ts, score=2)

        out = StringIO()
        call_command('cleanup_vozbox_pm', batch_size=2, stdout=out)

        assert set(PM25.objects.filter(monitor=self.monitor).values_list('stage', flat=True)) == {PM25.Stage.RAW}
        assert list(LatestEntry.objects.filter(monitor=self.monitor, entry_type='pm25')) == [raw_latest]
        assert not HealthCheck.objects.filter(monitor=self.monitor).exists()
        assert HealthCheck.objects.filter(pk=other_hc.pk).exists()
        self.monitor.refresh_from_db()
        assert self.monitor.health is None
        text = out.getvalue()
        assert 'pm25 legacy stages: 3 removed' in text
        assert 'pm25 legacy LatestEntry: 1 removed' in text
        assert 'health checks: 1 removed' in text
        assert 'removed 5 legacy rows' in text

    def test_monitor_id_filter(self):
        second = VOZBox.objects.create(sensor_id='e00fce68other', name='Other', location='outside')
        entry_models.PM25.objects.create(
            monitor=second, timestamp=datetime(2025, 6, 9, tzinfo=timezone.utc), sensor='a', stage='raw', value=1,
        )
        call_command('cleanup_vozbox_pm', monitor_ids=['e00fce68rename'], stdout=StringIO())
        assert self._sensors(entry_models.PM25, second) == {'a': 1}
        assert 'a' not in self._sensors(entry_models.PM25, self.monitor)
