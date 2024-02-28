from datetime import datetime, timedelta

from django.contrib.gis.db import models
from django.utils.dateparse import parse_datetime

from camp.apps.monitors.models import Monitor, Entry
from camp.utils.datetime import make_aware


class AQview(Monitor):
    LAST_ACTIVE_LIMIT = int(60 * 60 * 3)

    DATA_PROVIDERS = [{
        'name': 'California Air Resources Board',
        'url': 'https://arb.ca.gov'
    }]
    DATA_SOURCE = {
        'name': 'AQview',
        'url': 'https://aqview.arb.ca.gov/'
    }

    def process_entry(self, entry, payload):
        entry.timestamp = payload['timestamp']
        entry.pm25 = payload['aobs']
        entry.pm25_reported = payload['aobs']
        return super().process_entry(entry, payload)
