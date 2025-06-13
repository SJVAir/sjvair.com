import json

from datetime import timedelta

import requests

from django.conf import settings
from django.utils import timezone
from django.utils.translation import gettext as _
from resticus.encoders import JSONEncoder

from camp.utils.counties import County


# https://docs.airnowapi.org/webservices

class Requestor:
    def __init__(self, client=None):
        self.client = client
        self.session = self.make_session()

    def make_session(self):
        adapter = requests.adapters.HTTPAdapter(max_retries=5)
        session = requests.Session()
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        session.headers.update({"Accept": "application/json"})
        return session

    def get_headers(self, **kwargs):
        headers = {}
        headers.update(kwargs)
        return headers

    def request(self, url, method=None, **kwargs):
        method = method or "get"
        headers = self.get_headers(**kwargs.pop("headers", {}))

        data = kwargs.pop("json", None)
        if data is not None:
            kwargs["data"] = json.dumps(data, cls=JSONEncoder)
            headers["Content-Type"] = "application/json"

        response = self.session.request(method, url, **kwargs)
        response.is_success = lambda: response.ok
        response.is_error = lambda: not response.ok

        try:
            response.body = response.json()
        except Exception:
            response.body = {}

        return response


class AirNowClient:
    domain = "www.airnowapi.org"

    def __init__(self, api_key):
        self.api_key = api_key
        self.requestor = Requestor(self)

    def request(self, path, **kwargs):
        url = f"https://{self.domain}{path}"
        return self.requestor.request(url, **kwargs)

    def build_params(self, params, **extra):
        params.update(**extra)
        params.update({
            'api_key': self.api_key,
            'format': 'application/json',
        })
        return params

    def data(self, bbox, start_date, end_date, **kwargs):
        path = f"/aq/data/"
        params = self.build_params({
            'startdate': start_date.strftime('%Y-%m-%dT%H'),
            'enddate': end_date.strftime('%Y-%m-%dT%H'),
            'parameters': 'OZONE,PM25,PM10,CO,NO2,SO2',
            'bbox': ','.join(map(str, bbox)),
            'datatype': 'B',
            'verbose': 1,
            'nowcastonly': 0,
            'includerawconcentrations': 1,
        }, **kwargs)
        return self.request(path, method="get", params=params)

    def query(self, county, timestamp=None, previous=1, **kwargs):
        if timestamp is None:
            timestamp = timezone.now()

        response = self.data(
            bbox=County.counties[county].extent,
            start_date=timestamp - timedelta(hours=previous),
            end_date=timestamp,
            **kwargs,
        )

        data = {}
        for entry in response.json():
            data.setdefault(entry['SiteName'], {})
            data[entry['SiteName']].setdefault(entry['UTC'], {})
            data[entry['SiteName']][entry['UTC']][entry['Parameter']] = entry

        return data
    
    def query_ng(self, county, timestamp=None, previous=1, **kwargs):
        results = self.query(county, timestamp=timestamp, previous=previous, **kwargs)
        for container in results.values():
            for timestamp, data in container.items():
                for item in data.values():
                    yield item


airnow_api = AirNowClient(settings.AIRNOW_API_KEY)
