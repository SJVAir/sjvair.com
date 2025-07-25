from django.utils.dateparse import parse_datetime

from camp.apps.calibrations import processors
from camp.apps.entries import models as entry_models
from camp.apps.monitors.models import Monitor
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

    EXPECTED_INTERVAL = '1 hour'
    ENTRY_CONFIG = {
        entry_models.CO: {
            'fields': {'value': 'CO'},
            'allowed_stages': [entry_models.CO.Stage.RAW],
            'default_stage': entry_models.CO.Stage.RAW,
        },
        entry_models.NO2: {
            'fields': {'value': 'NO2'},
            'allowed_stages': [entry_models.NO2.Stage.RAW],
            'default_stage': entry_models.NO2.Stage.RAW,
        },
        entry_models.O3: {
            'fields': {'value': 'OZONE'},
            'allowed_stages': [entry_models.O3.Stage.RAW],
            'default_stage': entry_models.O3.Stage.RAW,
            'alerts': {'stage': entry_models.O3.Stage.RAW}
        },
        entry_models.PM25: {
            'fields': {'value': 'PM2.5'},
            'allowed_stages': [
                entry_models.PM25.Stage.RAW,
                entry_models.PM25.Stage.CLEANED,
            ],
            'default_stage': entry_models.PM25.Stage.CLEANED,
            'processors': {
                entry_models.PM25.Stage.RAW: [processors.PM25_FEM_Cleaner]
            },
            'alerts': {
                'stage': entry_models.PM25.Stage.CLEANED,
                'processor': processors.PM25_FEM_Cleaner,
            }
        },
        entry_models.PM100: {
            'fields': {'value': 'PM10'},
            'allowed_stages': [entry_models.PM100.Stage.RAW],
            'default_stage': entry_models.PM100.Stage.RAW,
        },
        entry_models.SO2: {
            'fields': {'value': 'SO2'},
            'allowed_stages': [entry_models.SO2.Stage.RAW],
            'default_stage': entry_models.SO2.Stage.RAW,
        },
    }

    ENTRY_MAP = {
        config['fields']['value']: EntryModel
        for EntryModel, config
        in ENTRY_CONFIG.items()
    }

    class Meta:
        verbose_name = 'AirNow'

    def handle_payload(self, payload):
        if EntryModel := self.ENTRY_MAP.get(payload['Parameter']):
            return self.create_entry(EntryModel,
                timestamp=make_aware(parse_datetime(payload['UTC'])),
                value=payload['Value']
            )


    # Legacy
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
