import csv
import io
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

from django.test import TestCase

from camp.apps.monitors.vozbox.api import VozBoxClient


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
