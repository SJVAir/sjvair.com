import html
import time

from datetime import timedelta

from django.contrib.gis.db import models
from django.contrib.gis.geos import Point

from camp.apps.calibrations import corrections
from camp.apps.entries import models as entry_models
from camp.apps.monitors.models import Monitor, Entry
from camp.apps.monitors.purpleair.api import purpleair_api
from camp.utils.datetime import parse_timestamp


class PurpleAir(Monitor):
    CALIBRATE = True  # legacy
    SENSORS = ['a', 'b']

    CHANNEL_FIELDS = {
        entry_models.PM10: {'value': 'pm1.0_atm'},
        entry_models.PM25: {'value': 'pm2.5_atm'},
        entry_models.PM100: {'value': 'pm10.0_atm'},
        entry_models.Particulates: {
            'particles_03um': '0.3_um_count',
            'particles_05um': '0.5_um_count',
            'particles_10um': '1.0_um_count',
            'particles_25um': '2.5_um_count',
            'particles_50um': '5.0_um_count',
            'particles_100um': '10.0_um_count',
        }
    }

    SINGLE_FIELDS = {
        entry_models.Temperature: {'value': 'temperature'},
        entry_models.Humidity: {'value': 'humidity'},
        entry_models.Pressure: {'value': 'pressure'},
    }

    CALIBRATIONS = {
        entry_models.PM25: [
            corrections.ColocLinearRegression,
            corrections.EPAPM25,
        ],
        entry_models.Temperature: [corrections.AirGradientTemperature],
        entry_models.Humidity: [corrections.AirGradientHumidity],
    }

    # Legacy
    CHANNEL_FIELDS_LEGACY = {
        'pm10': 'pm1.0_atm',
        'pm25': 'pm2.5_atm',
        'pm25_reported': 'pm2.5_atm',
        'pm100': 'pm10.0_atm',
        'particles_03um': '0.3_um_count',
        'particles_05um': '0.5_um_count',
        'particles_10um': '1.0_um_count',
        'particles_25um': '2.5_um_count',
        'particles_50um': '5.0_um_count',
        'particles_100um': '10.0_um_count',
    }

    # Legacy
    SENSOR_ATTRS = ['fahrenheit', 'humidity', 'pressure']
    SENSOR_ATTRS.extend(CHANNEL_FIELDS_LEGACY.keys())

    DATA_PROVIDERS = [{
        'name': 'PurpleAir',
        'url': 'https://www2.purpleair.com/'
    }]
    DATA_SOURCE = {
        'name': 'PurpleAir',
        'url': 'https://www2.purpleair.com/'
    }

    purple_id = models.IntegerField(unique=True)

    class Meta:
        verbose_name = 'PurpleAir'

    def update_data(self, data=None):
        if data is None:
            if self.purple_id is None:
                raise ValueError(f'Cannot fetch Purple Air data if purple_id is None.')
            data = purpleair_api.get_sensor(self.purple_id)

        self.name = html.unescape(data['name'])
        self.position = Point(
            float(data['longitude']),
            float(data['latitude'])
        )
        self.location = self.get_probable_location(data)
        self.device = data.get('model', '')

        if not self.default_sensor:
            self.default_sensor = 'a'

    def get_probable_location(self, data):
        # Check for an explicit flag
        if data['location_type'] == 1:
            return self.LOCATION.inside

        # If the name says it's inside, it probably is
        name = data['name'].lower()
        inside_list = ('inside', 'indoor', 'in door', 'in-door')
        if any(item in name for item in inside_list):
            return self.LOCATION.inside

        # If we're here, it's probably outside.
        return self.LOCATION.outside

    def create_entries(self, payload):
        timestamp = parse_timestamp(payload.get('last_seen', payload.get('time_stamp')))
        entries = []

        for sensor in self.SENSORS:
            for EntryModel, fields in self.CHANNEL_FIELDS.items():
                if entry := self.create_entry_ng(
                    EntryModel=EntryModel,
                    timestamp=timestamp,
                    sensor=sensor,
                    **{k: payload.get(f'{v}_{sensor}') for k, v in fields.items()}
                ) is not None:
                    entries.append(entry)

        for EntryModel, fields in self.SINGLE_FIELDS.items():
            if entry := self.create_entry_ng(
                EntryModel=EntryModel,
                timestamp=timestamp,
                **{k: payload.get(v) for k, v in fields.items()}
            ) is not None:
                entries.append(entry)

        self.calibrate_entries(entries)
        return entries

    def create_entry_ng(self, EntryModel, **data):
        if data and all(map(lambda x: x is not None, data.values())):
            return super().create_entry_ng(EntryModel, **data)

    # Legacy
    def create_entries_legacy(self, payload):
        return [self.create_entry_legacy(data, data['sensor'])
            for data in self._split_channels(payload)]

    def create_entry_legacy(self, payload, sensor=None):
        try:
            entry = self.entries.get(
                sensor=sensor,
                timestamp=payload['timestamp'],
            )
            entry = self.process_entry(entry, payload)
            entry.save()
            return entry
        except Entry.DoesNotExist:
            return super().create_entry(payload, sensor=sensor)

    def _split_channels(self, payload):
        '''
            The Purple Air API returns a single object with data
            from both channels A and B. This method splits that into
            two data structures that can be saved independently.
        '''
        base_data = {
            'timestamp': parse_timestamp(payload.get('last_seen', payload.get('time_stamp'))),
            'fahrenheit': payload['temperature'],
            'humidity': payload['humidity'],
            'pressure': payload['pressure'],
        }

        for sensor in self.SENSORS:
            # If no PM2.5 data on this channel, skip it.
            if payload.get(f'{self.CHANNEL_FIELDS_LEGACY["pm25"]}_{sensor}') is None:
                continue

            data = base_data.copy()
            data.update(sensor=sensor, **{
                target: payload[f'{source}_{sensor}']
                for target, source in self.CHANNEL_FIELDS_LEGACY.items()
            })

            yield data


    def process_entry(self, entry, payload):
        # The fields are already correctly mapped in the _split_channels
        # method, so we just need to copy 'em over.

        for attr in self.SENSOR_ATTRS:
            if payload.get(attr) is not None:
                setattr(entry, attr, payload[attr])

        entry.timestamp = payload['timestamp']
        return super().process_entry(entry, payload)
