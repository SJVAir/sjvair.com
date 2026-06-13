from django.contrib.gis.db import models
from django.contrib.gis.geos import Point
from django.utils.translation import gettext_lazy as _

from camp.apps.calibrations import processors
from camp.apps.entries import models as entry_models
from camp.apps.monitors.models import Monitor


class VOZBox(Monitor):
    DATA_PROVIDERS = [{'name': 'CCEJN', 'url': 'https://ccejn.org/'}]
    DATA_SOURCE = {'name': 'VOZbox', 'url': 'https://ccejn.org/'}
    EXPECTED_INTERVAL = '10 min'
    GRADE = Monitor.Grade.LCS

    ENTRY_CONFIG = {
        entry_models.PM10: {
            'sensors': ['a', 'b'],
            'allowed_stages': [entry_models.PM10.Stage.RAW],
            'default_stage': entry_models.PM10.Stage.RAW,
        },
        entry_models.PM25: {
            'sensors': ['a', 'b'],
            'allowed_stages': [
                entry_models.PM25.Stage.RAW,
                entry_models.PM25.Stage.CORRECTED,
                entry_models.PM25.Stage.CLEANED,
                entry_models.PM25.Stage.CALIBRATED,
            ],
            'default_stage': entry_models.PM25.Stage.CLEANED,
            'processors': {
                entry_models.PM25.Stage.RAW: [processors.PM25_LCS_Correction],
                entry_models.PM25.Stage.CORRECTED: [processors.PM25_LCS_Cleaning],
                entry_models.PM25.Stage.CLEANED: [
                    processors.PM25_UnivariateLinearRegression,
                    processors.PM25_MultivariateLinearRegression,
                    processors.PM25_EPA_Oct2021,
                ],
            },
            'alerts': {
                'stage': entry_models.PM25.Stage.CALIBRATED,
                'processor': processors.PM25_UnivariateLinearRegression,
            },
        },
        entry_models.PM100: {
            'sensors': ['a', 'b'],
            'allowed_stages': [entry_models.PM100.Stage.RAW],
            'default_stage': entry_models.PM100.Stage.RAW,
        },
        entry_models.Temperature: {
            'sensors': ['1'],
            'allowed_stages': [entry_models.Temperature.Stage.RAW],
            'default_stage': entry_models.Temperature.Stage.RAW,
        },
        entry_models.Humidity: {
            'sensors': ['1'],
            'allowed_stages': [entry_models.Humidity.Stage.RAW],
            'default_stage': entry_models.Humidity.Stage.RAW,
        },
        entry_models.O3: {
            'sensors': ['1'],
            'allowed_stages': [
                entry_models.O3.Stage.RAW,
                entry_models.O3.Stage.CALIBRATED,
            ],
            'default_stage': entry_models.O3.Stage.RAW,
            'processors': {
                entry_models.O3.Stage.RAW: [processors.O3_VOZBox],
            },
        },
    }

    sensor_id = models.CharField(_('sensor ID'), max_length=64, unique=True)

    class Meta:
        verbose_name = 'VOZbox'

    def update_data(self, row):
        if not self.name:
            self.name = self.sensor_id
        if row.get('latitude') and row.get('longitude'):
            self.position = Point(float(row['longitude']), float(row['latitude']), srid=4326)
        self.location = self.LOCATION.outside

    def create_entries(self, row):
        timestamp = row['timestamp']
        entries = []

        dual_channel = {
            'a': {
                entry_models.PM10: {'value': row.get('pm1_a')},
                entry_models.PM25: {'value': row.get('pm25_a')},
                entry_models.PM100: {'value': row.get('pm10_a')},
            },
            'b': {
                entry_models.PM10: {'value': row.get('pm1_b')},
                entry_models.PM25: {'value': row.get('pm25_b')},
                entry_models.PM100: {'value': row.get('pm10_b')},
            },
        }
        single_channel = {
            entry_models.Temperature: {'celsius': row.get('temperature')},
            entry_models.Humidity: {'value': row.get('humidity')},
            entry_models.O3: {'value': row.get('o3')},
        }

        for sensor, model_map in dual_channel.items():
            for EntryModel, data in model_map.items():
                entry = self.create_entry(EntryModel, timestamp=timestamp, sensor=sensor, **data)
                if entry is not None:
                    entries.append(entry)

        for EntryModel, data in single_channel.items():
            entry = self.create_entry(EntryModel, timestamp=timestamp, sensor='1', **data)
            if entry is not None:
                entries.append(entry)

        return entries

    def create_entry(self, EntryModel, **data):
        skip_keys = {'timestamp', 'sensor'}
        values = {k: v for k, v in data.items() if k not in skip_keys}
        if any(v is None for v in values.values()):
            return None
        return super().create_entry(EntryModel, **data)
