from datetime import datetime, timedelta

from django.conf import settings
from django.contrib.gis.db import models

from camp.apps.entries import models as entry_models
from camp.apps.monitors.models import Monitor


class CIMIS(Monitor):
    LAST_ACTIVE_LIMIT = int(60 * 60 * 3)

    DATA_PROVIDERS = [{
        'name': 'California Department of Water Resources',
        'url': 'https://water.ca.gov',
    }]
    DATA_SOURCE = {
        'name': 'CIMIS',
        'url': 'https://cimis.water.ca.gov/',
    }
    DEVICE = 'CIMIS Weather Station'

    EXPECTED_INTERVAL = '1h'
    ENTRY_CONFIG = {
        entry_models.Temperature: {
            'fields': {'value': 'HlyAirTmp'},
            'allowed_stages': [entry_models.Temperature.Stage.RAW],
            'default_stage': entry_models.Temperature.Stage.RAW,
        },
        entry_models.Humidity: {
            'fields': {'value': 'HlyRelHum'},
            'allowed_stages': [entry_models.Humidity.Stage.RAW],
            'default_stage': entry_models.Humidity.Stage.RAW,
        },
        entry_models.DewPoint: {
            'fields': {'value': 'HlyDewPnt'},
            'allowed_stages': [entry_models.DewPoint.Stage.RAW],
            'default_stage': entry_models.DewPoint.Stage.RAW,
        },
        entry_models.SoilTemperature: {
            'fields': {'value': 'HlySoilTmp'},
            'allowed_stages': [entry_models.SoilTemperature.Stage.RAW],
            'default_stage': entry_models.SoilTemperature.Stage.RAW,
        },
        entry_models.WindSpeed: {
            'fields': {'value': 'HlyWindSpd'},
            'allowed_stages': [entry_models.WindSpeed.Stage.RAW],
            'default_stage': entry_models.WindSpeed.Stage.RAW,
        },
        entry_models.WindDirection: {
            'fields': {'value': 'HlyWindDir'},
            'allowed_stages': [entry_models.WindDirection.Stage.RAW],
            'default_stage': entry_models.WindDirection.Stage.RAW,
        },
        entry_models.Precipitation: {
            'fields': {'value': 'HlyPrecip'},
            'allowed_stages': [entry_models.Precipitation.Stage.RAW],
            'default_stage': entry_models.Precipitation.Stage.RAW,
        },
        entry_models.SolarRadiation: {
            'fields': {'value': 'HlySolRad'},
            'allowed_stages': [entry_models.SolarRadiation.Stage.RAW],
            'default_stage': entry_models.SolarRadiation.Stage.RAW,
        },
        entry_models.NetRadiation: {
            'fields': {'value': 'HlyNetRad'},
            'allowed_stages': [entry_models.NetRadiation.Stage.RAW],
            'default_stage': entry_models.NetRadiation.Stage.RAW,
        },
        entry_models.VaporPressure: {
            'fields': {'value': 'HlyVapPres'},
            'allowed_stages': [entry_models.VaporPressure.Stage.RAW],
            'default_stage': entry_models.VaporPressure.Stage.RAW,
        },
        entry_models.ETo: {
            'fields': {'value': 'HlyAsceEto'},
            'allowed_stages': [entry_models.ETo.Stage.RAW],
            'default_stage': entry_models.ETo.Stage.RAW,
        },
        entry_models.ETr: {
            'fields': {'value': 'HlyAsceEtr'},
            'allowed_stages': [entry_models.ETr.Stage.RAW],
            'default_stage': entry_models.ETr.Stage.RAW,
        },
    }

    GRADE = None

    station_number = models.CharField(max_length=20, unique=True)

    class Meta:
        verbose_name = 'CIMIS'

    ENTRY_MAP = {
        config['fields']['value']: EntryModel
        for EntryModel, config in ENTRY_CONFIG.items()
    }

    def parse_timestamp(self, record):
        date_str = record['Date']
        hour_str = record['Hour'].zfill(4)

        if hour_str == '2400':
            base = datetime.strptime(date_str, '%Y-%m-%d') + timedelta(days=1)
            naive = base.replace(hour=0, minute=0)
        else:
            naive = datetime.strptime(f'{date_str} {hour_str}', '%Y-%m-%d %H%M')

        return naive.replace(tzinfo=settings.DEFAULT_TIMEZONE)

    def handle_payload(self, record):
        timestamp = self.parse_timestamp(record)
        entries = []

        for field_name, EntryModel in self.ENTRY_MAP.items():
            item = record.get(field_name)
            if not item:
                continue

            if item.get('Qc') == 'N':
                continue

            value = item.get('Value')
            if value in (None, ''):
                continue

            entry = self.create_entry(EntryModel, timestamp=timestamp, value=value)
            if entry:
                entries.append(entry)

        return entries
