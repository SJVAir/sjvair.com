from datetime import timedelta

import urllib.parse

import requests

from django.utils import timezone


class AQLiteAPI:
    API_URL = 'https://air.api.airqdb.com/v2/'

    def __init__(self, key):
        self.key = key

    def build_url(self, path):
        return urllib.parse.urljoin(self.API_URL, path)

    def build_headers(self, headers=None):
        defaults = {
            'Accept': 'application/json',
            'x-company-key': self.key,
        }
        if headers:
            defaults.update(headers)
        return defaults

    def request(self, path, method=None, **kwargs):
        method = method or 'get'
        url = self.build_url(path)
        headers = self.build_headers(kwargs.pop('headers', None))
        kwargs.setdefault('timeout', 30)
        response = requests.request(method, url, headers=headers, **kwargs)
        response.raise_for_status()
        return response

    def get(self, path, **kwargs):
        return self.request(path, 'get', **kwargs)

    def get_time_series(self, device_id, start=None, end=None, average=0):
        end = end or timezone.now()
        start = start or end - timedelta(hours=24)
        params = {
            'average': str(average),
            'start': start.isoformat(),
            'end': end.isoformat(),
        }
        response = self.get(f'uploads/primary/time-series/{device_id}', params=params)
        return response.json()
