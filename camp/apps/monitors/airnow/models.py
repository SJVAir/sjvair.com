from django.contrib.gis.db import models
from django.utils.dateparse import parse_datetime

from camp.apps.entries import models as entry_models
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

    ENTRY_MAP = {
        'CO': (entry_models.CO, 'co'),
        'NO2': (entry_models.NO2, 'no2'),
        'OZONE': (entry_models.O3, 'o3'),
        'PM2.5': (entry_models.PM25, 'pm25_reported'),
        'PM10': (entry_models.PM100, 'pm100'),
    }

    class Meta:
        verbose_name = 'AirNow'

    def create_entries(self, payload):
        entries = []
        timestamp = make_aware(parse_datetime(
            list(payload.values())[0]['UTC']
        ))

        for key, data in payload.items():
            EntryModel, attr = self.ENTRY_MAP.get(key)
            if EntryModel is None:
                continue

            if entry := self.create_entry_ng(EntryModel,
                timestamp=timestamp,
                **{attr: data['Value']}
            ) is not None:
                entries.append(entry)

        return entries



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
