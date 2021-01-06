from django.contrib.gis.db import models
from django.utils.dateparse import parse_datetime

from camp.apps.monitors.models import Monitor, Entry


class AirNow(Monitor):
    LAST_ACTIVE_LIMIT = int(60 * 60 * 1.5)

    def process_entry(self, entry):
        entry.timestamp = parse_datetime(
            list(entry.payload.values())[0]['UTC']
        )
        if 'PM2.5' in entry.payload:
            entry.pm25_env = entry.payload['PM2.5']['Value']
            entry.pm25_aqi = entry.payload['PM2.5']['AQI']
        if 'PM10' in entry.payload:
            entry.pm100_env = entry.payload['PM10']['Value']
        return super().process_entry(entry)
