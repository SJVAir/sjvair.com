from django.utils.dateparse import parse_datetime

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

    ENTRY_CONFIG = {
        entry_models.CO: {
            'fields': {'value': 'CO'},
            'allowed_stages': [entry_models.CO.Stage.REFERENCE],
            'default_stage': entry_models.CO.Stage.REFERENCE,
        },
        entry_models.NO2: {
            'fields': {'value': 'NO2'},
            'allowed_stages': [entry_models.NO2.Stage.REFERENCE],
            'default_stage': entry_models.NO2.Stage.REFERENCE,
        },
        entry_models.O3: {
            'fields': {'value': 'OZONE'},
            'allowed_stages': [entry_models.O3.Stage.REFERENCE],
            'default_stage': entry_models.O3.Stage.REFERENCE,
        },
        entry_models.PM25: {
            'fields': {'value': 'PM2.5'},
            'allowed_stages': [entry_models.PM25.Stage.REFERENCE],
            'default_stage': entry_models.PM25.Stage.REFERENCE,
        },
        entry_models.PM100: {
            'fields': {'value': 'PM10'},
            'allowed_stages': [entry_models.PM100.Stage.REFERENCE],
            'default_stage': entry_models.PM100.Stage.REFERENCE,
        },
        entry_models.SO2: {
            'fields': {'value': 'SO2'},
            'allowed_stages': [entry_models.SO2.Stage.REFERENCE],
            'default_stage': entry_models.SO2.Stage.REFERENCE,
        },
    }

    ENTRY_MAP = {
        config['fields']['value']: EntryModel
        for EntryModel, config
        in ENTRY_CONFIG.items()
    }

    class Meta:
        verbose_name = 'AirNow'

    def create_entries(self, payload):
        EntryModel = self.ENTRY_MAP.get(payload['Parameter'])
        if EntryModel is not None:
            if entry := super().create_entry(EntryModel,
                timestamp=make_aware(parse_datetime(payload['UTC'])),
                value=payload['Value']
            ) is not None:
                return [entry]
        return []
    
    def create_entry(self, payload):
        EntryModel = self.ENTRY_MAP.get(payload['Parameter'])
        if EntryModel is not None:
            timestamp = make_aware(parse_datetime(payload['UTC']))
            return super().create_entry(EntryModel,
                timestamp=timestamp,
                value=payload['Value']
            )

    # def create_entries(self, payload):
    #     entries = []
    #     timestamp = make_aware(parse_datetime(
    #         list(payload.values())[0]['UTC']
    #     ))

    #     for key, data in payload.items():
    #         EntryModel = self.ENTRY_MAP.get(key)
    #         if EntryModel is None:
    #             continue

    #         if entry := self.create_entry_ng(EntryModel,
    #             timestamp=timestamp,
    #             value=data['Value']
    #         ) is not None:
    #             entries.append(entry)

    #     return entries


    # Legacy
    def process_entry_legacy(self, entry, payload):
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
