import json
import time

from datetime import date, datetime, timedelta
from random import random
from typing import Sequence, Iterator, Dict, Any, Optional

import requests

from django.conf import settings
from django.utils import timezone
from django.utils.translation import gettext as _
from resticus.encoders import JSONEncoder

from camp.apps.regions.models import Region
from camp.utils.datetime import chunk_date_range


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

    def request(self, path: str, **kwargs: Any) -> requests.Response:
        url = f'https://{self.domain}{path}'
        return self.requestor.request(url, **kwargs)

    def build_params(self, params: Dict[str, Any], **extra: Any) -> Dict[str, Any]:
        params.update(**extra)
        params.update({
            'api_key': self.api_key,
            'format': 'application/json',
        })
        return params

    def data(self,
        bbox: Sequence[float],
        start_date: Optional[datetime],
        end_date: Optional[datetime],
        **kwargs: Any,
    ):
        path = '/aq/data/'
        base = {
            'parameters': 'OZONE,PM25,PM10,CO,NO2,SO2',
            'bbox': ','.join(map(str, bbox)),
            'datatype': 'C',
            'verbose': 1,
            'nowcastonly': 0,
            'includerawconcentrations': 1,
        }

        if start_date:
            base['startdate'] = start_date.strftime('%Y-%m-%dT%H')

        if end_date:
            base['enddate']   = end_date.strftime('%Y-%m-%dT%H')

        params = self.build_params(base, **kwargs)
        return self.request(path, method='get', params=params)

    def query(
        self,
        *,
        bbox: Sequence[float],
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        batch_days: int = 7,
        pause_secs: float = 0.2,
        **kwargs: Any,
    ) -> Iterator[Dict[str, Any]]:

        end_date = end_date or timezone.now()
        start_date = start_date or end_date - timedelta(hours=1)

        windows = chunk_date_range(start_date, end_date, days=batch_days)
        for idx, (win_start, win_end) in enumerate(windows):
            response = self.data(bbox=bbox, start_date=win_start, end_date=win_end, **kwargs)

            # handle rate limit
            if response.status_code == 429:
                wait = max(1.0, random() * 5.0)
                time.sleep(wait)
                response = self.data(bbox=bbox, start_date=win_start, end_date=win_end, **kwargs)

            for entry in response.json():
                yield entry

            if idx + 1 < len(windows):
                time.sleep(pause_secs)

    def query_legacy(self, bbox, timestamp=None, previous=1, **kwargs):
        if timestamp is None:
            timestamp = timezone.now()

        response = self.data(
            bbox=bbox,
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


airnow_api = AirNowClient(settings.AIRNOW_API_KEY)
