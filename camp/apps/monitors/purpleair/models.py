import time

from datetime import timedelta

from django.contrib.gis.db import models
from django.contrib.gis.geos import Point
from django.contrib.postgres.fields import JSONField
from django.utils.functional import cached_property

from resticus.encoders import JSONEncoder

from camp.apps.monitors.models import Monitor, Entry
from camp.apps.monitors.purpleair.api import purpleair_api
from camp.utils.datetime import parse_timestamp


class PurpleAir(Monitor):
    SENSORS = ['a', 'b']
    CHANNEL_FIELDS = {
        'pm10': 'pm1.0_atm',
        'pm25': 'pm2.5_atm',
        'pm100': 'pm10.0_atm',
        'particles_03um': '0.3_um_count',
        'particles_05um': '0.5_um_count',
        'particles_10um': '1.0_um_count',
        'particles_25um': '2.5_um_count',
        'particles_50um': '5.0_um_count',
        'particles_100um': '10.0_um_count',
    }

    SENSOR_ATTRS = ['fahrenheit', 'humidity', 'pressure']
    SENSOR_ATTRS.extend(CHANNEL_FIELDS.keys())

    data = JSONField(default=dict, encoder=JSONEncoder)

    @cached_property
    def purple_id(self):
        return self.data['sensor_index']

    @cached_property
    def thingspeak_key(self):
        return self.data['primary_key_a']

    def update_data(self, device_data=None, retries=3):
        if device_data is None:
            device_data = purpleair_api.get_sensor(self.purple_id, self.thingspeak_key)

        self.data = device_data
        self.name = self.data['name']
        self.position = Point(
            float(self.data['longitude']),
            float(self.data['latitude'])
        )
        self.location = self.LOCATION.inside if self.data['location_type'] == 1 else self.LOCATION.outside

        if not self.default_sensor:
            self.default_sensor = 'a'

    def create_entry(self, payload, sensor=None):
        try:
            return self.entries.get(
                sensor=sensor,
                timestamp=payload['timestamp'],
            )
        except Entry.DoesNotExist:
            return super().create_entry(payload, sensor=sensor)

    def create_entries(self, payload):
        a_data, b_data = self._split_channels(payload)
        a = self.create_entry(a_data, 'a')
        b = self.create_entry(b_data, 'b')
        return (a, b)

    def _split_channels(self, payload):
        '''
            The PUrple Air API returns a single object with data
            from both channels A and B. This methid splits that into
            two data structures that can eb saved independently.
        '''
        data = {
            'timestamp': parse_timestamp(payload['last_seen']),
            'fahrenheit': payload['temperature'],
            'humidity': payload['humidity'],
            'pressure': payload['pressure'],
        }

        channels = []
        for channel in ('a', 'b'):
            channels.append(data.copy())
            for target, source in self.CHANNEL_FIELDS.items():
                channels[-1][target] = payload[f'{source}_{channel}']

        return channels

    def process_entry(self, entry):
        # The fields are already correctly mapped in the _split_channels
        # method, so we just need to copy 'em over and set the timestamp.
        for attr in self.SENSOR_ATTRS:
            if entry.payload.get(attr):
                setattr(entry, attr, entry.payload[attr])

        entry.timestamp = parse_timestamp(entry.payload.get('timestamp'))
        return super().process_entry(entry)
