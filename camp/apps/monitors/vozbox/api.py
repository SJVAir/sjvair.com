import csv
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

import requests
from django.conf import settings


class VozBoxClient:
    OWNER = 'QuinnResearch'
    REPO = 'carbVoz_data'
    GITHUB_API = 'https://api.github.com'
    RAW_BASE = 'https://raw.githubusercontent.com'
    BRANCH = 'main'

    DAILY_FOLDER = 'moospmV3_daily'
    DAILY_PREFIX = 'moospmV3'
    CAL_FOLDER = 'moospmV3_cal'
    CAL_PREFIX = 'moospmV3_cal'

    def __init__(self):
        self._tmpdir = None
        self._session = None

    def __enter__(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        return self

    def __exit__(self, *args):
        if self._tmpdir:
            self._tmpdir.cleanup()
            self._tmpdir = None
        if self._session:
            self._session.close()
            self._session = None

    @property
    def session(self):
        if self._session is None:
            self._session = requests.Session()
            token = getattr(settings, 'GITHUB_API_TOKEN', None)
            if token:
                self._session.headers['Authorization'] = f'Bearer {token}'
        return self._session

    def _raw_url(self, folder, filename):
        return f'{self.RAW_BASE}/{self.OWNER}/{self.REPO}/{self.BRANCH}/{folder}/{filename}'

    def _api_url(self, path):
        return f'{self.GITHUB_API}/repos/{self.OWNER}/{self.REPO}/contents/{path}'

    def daily_filename(self, d: date) -> str:
        return f'{self.DAILY_PREFIX}_{d.strftime("%Y-%m-%d")}.csv'

    def cal_filename(self, d: date, hour_utc: int) -> str:
        return f'{self.CAL_PREFIX}_{d.strftime("%Y-%m-%d")}T{hour_utc:02d}.csv'

    def download_csv(self, url: str) -> Optional[Path]:
        if self._tmpdir is None:
            raise RuntimeError('VozBoxClient must be used as a context manager')
        response = self.session.get(url)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        filename = url.rsplit('/', 1)[-1]
        path = Path(self._tmpdir.name) / filename
        path.write_text(response.text, encoding='utf-8')
        return path

    def parse_csv(self, path: Path) -> dict:
        result = {}
        with path.open(encoding='utf-8') as fh:
            for raw_row in csv.DictReader(fh):
                coreid = raw_row.get('coreid', '').strip()
                if not coreid:
                    continue
                row = self._normalize_row(raw_row)
                if row is None:
                    continue
                result.setdefault(coreid, []).append(row)
        return result

    def _normalize_row(self, raw: dict) -> Optional[dict]:
        try:
            ts = datetime.fromtimestamp(int(raw['unixtime']), tz=timezone.utc)
        except (KeyError, ValueError, TypeError):
            return None

        def _float(key):
            val = raw.get(key, '').strip()
            try:
                return float(val)
            except (ValueError, TypeError):
                return None

        def _pm(key):
            val = _float(key)
            if val is not None and val > 9999:
                return None
            return val

        return {
            'timestamp': ts,
            'pm1_a': _pm('m_PM1_ATM'),
            'pm1_b': _pm('m_PM1_b'),
            'pm25_a': _pm('m_PM25_ATM'),
            'pm25_b': _pm('m_PM25_b'),
            'pm10_a': _pm('m_PM10_ATM'),
            'pm10_b': _pm('m_PM10_b'),
            'temperature': _float('temp_C'),
            'humidity': _float('rh'),
            'o3': _float('o3'),
            'o3_cal': _float('o3_cal'),
            'latitude': _float('lat'),
            'longitude': _float('lon'),
        }

    def get_daily_data(self, d: date) -> Optional[dict]:
        url = self._raw_url(self.DAILY_FOLDER, self.daily_filename(d))
        path = self.download_csv(url)
        if path is None:
            return None
        return self.parse_csv(path)

    def get_cal_data(self, d: date, hour_utc: int) -> Optional[dict]:
        url = self._raw_url(self.CAL_FOLDER, self.cal_filename(d, hour_utc))
        path = self.download_csv(url)
        if path is None:
            return None
        return self.parse_csv(path)

    def list_daily_files(self) -> list:
        url = self._api_url(self.DAILY_FOLDER)
        response = self.session.get(url)
        response.raise_for_status()
        results = []
        for item in response.json():
            name = item.get('name', '')
            if not (name.startswith(self.DAILY_PREFIX + '_') and name.endswith('.csv')):
                continue
            try:
                results.append(date.fromisoformat(name[len(self.DAILY_PREFIX) + 1:-4]))
            except ValueError:
                continue
        return sorted(results)

    def list_cal_files(self) -> list:
        url = self._api_url(self.CAL_FOLDER)
        response = self.session.get(url)
        response.raise_for_status()
        results = []
        for item in response.json():
            name = item.get('name', '')
            if not (name.startswith(self.CAL_PREFIX + '_') and name.endswith('.csv')):
                continue
            try:
                stem = name[len(self.CAL_PREFIX) + 1:-4]   # "2025-06-20T15"
                date_part, hour_part = stem.split('T')
                results.append((date.fromisoformat(date_part), int(hour_part)))
            except (ValueError, IndexError):
                continue
        return sorted(results)
