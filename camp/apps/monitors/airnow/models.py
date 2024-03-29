from django.contrib.gis.db import models
from django.utils.dateparse import parse_datetime

from camp.apps.monitors.models import Monitor, Entry
from camp.utils.datetime import make_aware


class AirNow(Monitor):
    LAST_ACTIVE_LIMIT = int(60 * 60 * 1.5)

    DATA_PROVIDERS = [{
        'name': 'AirNow Partners',
        'url': 'https://www.airnow.gov/partners/'
    }]
    DATA_SOURCE = {
        'name': 'AirNow.gov',
        'url': 'https://www.airnow.gov/'
    }
    DEVICE = 'BAM 1022'

    class Meta:
        verbose_name = 'AirNow'

    def process_entry(self, entry, payload):
        entry.timestamp = make_aware(parse_datetime(
            list(payload.values())[0]['UTC']
        ))
        if 'PM2.5' in payload:
            entry.pm25 = payload['PM2.5']['Value']
            entry.pm25_reported = payload['PM2.5']['Value']
        if 'PM10' in payload:
            entry.pm100 = payload['PM10']['Value']
        if 'OZONE' in payload:
            entry.ozone = payload['OZONE']['Value']
        return super().process_entry(entry, payload)
