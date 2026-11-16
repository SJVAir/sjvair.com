from django.utils.dateparse import parse_datetime

from camp.apps.calibrations import processors
from camp.apps.calibrations.core.processors.airnow import AirNowNowCast
from camp.apps.entries import models as entry_models
from camp.apps.monitors.models import Monitor
from camp.utils.datetime import make_aware


class AirNow(Monitor):
    # An hour's RawConcentration (our RAW) first shows up about 1h20m after
    # the hour starts, so the newest RAW is 1h20m to 2h20m old.
    LAST_ACTIVE_LIMIT = int(60 * 60 * 3)

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
            'allowed_stages': [
                entry_models.O3.Stage.RAW,
                entry_models.O3.Stage.CALIBRATED,
            ],
            'default_stage': entry_models.O3.Stage.RAW,
            'alerts': {'stage': entry_models.O3.Stage.RAW},
            'calibrations': [processors.O3_AirNow_NowCast],
        },
        entry_models.PM25: {
            'fields': {'value': 'PM2.5'},
            'allowed_stages': [
                entry_models.PM25.Stage.RAW,
                entry_models.PM25.Stage.CLEANED,
                entry_models.PM25.Stage.CALIBRATED,
            ],
            'default_stage': entry_models.PM25.Stage.CLEANED,
            'processors': {
                entry_models.PM25.Stage.RAW: [processors.PM25_FEM_Cleaner]
            },
            'calibrations': [processors.PM25_AirNow_NowCast],
            'alerts': {
                'stage': entry_models.PM25.Stage.CLEANED,
                'processor': processors.PM25_FEM_Cleaner,
            }
        },
        entry_models.PM100: {
            'fields': {'value': 'PM10'},
            'allowed_stages': [
                entry_models.PM100.Stage.RAW,
                entry_models.PM100.Stage.CALIBRATED,
            ],
            'default_stage': entry_models.PM100.Stage.RAW,
            # AirNow's own NowCast, stored alongside the hourly value.
            'calibrations': [processors.PM100_AirNow_NowCast],
        },
        entry_models.SO2: {
            'fields': {'value': 'SO2'},
            'allowed_stages': [entry_models.SO2.Stage.RAW],
            'default_stage': entry_models.SO2.Stage.RAW,
        },
    }

    GRADE = Monitor.Grade.FEM

    ENTRY_MAP = {
        config['fields']['value']: EntryModel
        for EntryModel, config
        in ENTRY_CONFIG.items()
    }

    # AirNow's `Value` for these is the NowCast, not the hourly reading;
    # `RawConcentration` is the instrument's hourly value, stored as RAW,
    # and the NowCast is kept as CALIBRATED by the named processor. For
    # CO, NO2, and SO2 `Value` is already the hourly reading.
    NOWCAST_PROCESSORS = {
        'PM2.5': processors.PM25_AirNow_NowCast,
        'PM10': processors.PM100_AirNow_NowCast,
        'OZONE': processors.O3_AirNow_NowCast,
    }

    @classmethod
    def get_timestamp(cls, payload):
        return make_aware(parse_datetime(payload['UTC']))

    @classmethod
    def get_value(cls, payload):
        if payload['Parameter'] in cls.NOWCAST_PROCESSORS:
            return payload['RawConcentration']
        return payload['Value']

    class Meta:
        verbose_name = 'AirNow'

    def handle_payload(self, payload):
        if EntryModel := self.ENTRY_MAP.get(payload['Parameter']):
            entry = raw = None
            if not AirNowNowCast.is_missing(value := self.get_value(payload)):
                timestamp = self.get_timestamp(payload)
                entry = self.create_entry(EntryModel, timestamp=timestamp, value=value)
                # create_entry returns None when the stored RAW is unchanged.
                raw = entry or EntryModel.objects.filter(
                    monitor_id=self.pk,
                    timestamp=timestamp,
                    sensor='',
                    stage=EntryModel.Stage.RAW,
                ).first()

            # Saved even when the hour's RAW is missing: AirNow's NowCast
            # only needs 2 of the last 3 hours.
            if processor := self.NOWCAST_PROCESSORS.get(payload['Parameter']):
                processor.create_entry(self, payload, origin=raw)
            return entry

    # Legacy
    def process_entry(self, entry, payload):
        entry.timestamp = make_aware(parse_datetime(
            list(payload.values())[0]['UTC']
        ))
        if 'PM2.5' in payload:
            entry.pm25 = self.get_value(payload['PM2.5'])
            entry.pm25_reported = self.get_value(payload['PM2.5'])
        if 'PM10' in payload:
            entry.pm100 = self.get_value(payload['PM10'])
        if 'OZONE' in payload:
            entry.ozone = self.get_value(payload['OZONE'])
        return super().process_entry(entry, payload)
