import time

from django.contrib.gis.db import models
from django.contrib.gis.geos import Point
from django.contrib.postgres.fields import JSONField
from django.utils.functional import cached_property

from resticus.encoders import JSONEncoder

from camp.apps.monitors.models import Monitor, Entry
from camp.apps.monitors.purpleair import api


class PurpleAir(Monitor):
    DEFAULT_SENSOR = 'a'

    data = JSONField(default=dict, encoder=JSONEncoder)

    @cached_property
    def purple_id(self):
        return self.data[0]['ID']

    @cached_property
    def thingspeak_key(self):
        return self.data[0]['THINGSPEAK_PRIMARY_ID_READ_KEY']

    def get_devices(self, retries=3):
        devices = api.get_devices(self.purple_id, self.thingspeak_key)
        if devices is None and retries:
            time.sleep(5 * (4 - retries))
            return self.get_devices(retries - 1)
        return devices

    @cached_property
    def channels(self):
        return api.get_channels(self.data)

    def get_feeds(self, **options):
        return {
            'a': api.get_feeds(self.channels['a'], **options),
            'b': api.get_feeds(self.channels['b'], **options)
        }
        return api.get_feeds(self.channels, **options)

    def update_data(self, device_data=None, retries=3):
        if device_data is None:
            device_data = self.get_devices()

        self.data = device_data
        self.name = self.data[0]['Label']
        self.position = Point(
            float(self.data[0]['Lon']),
            float(self.data[0]['Lat'])
        )
        self.location = self.data[0]['DEVICE_LOCATIONTYPE']

    def create_entry(self, payload, sensor=None):
        try:
            return self.entries.get(
                sensor=sensor,
                timestamp=payload[0]['created_at'],
            )
        except Entry.DoesNotExist:
            return super().create_entry(payload, sensor=sensor)

    def process_entry(self, entry):
        attr_map = {
            'fahrenheit': 'Temperature',
            'humidity': 'Humidity',
            'pressure': 'Pressure',
            'pm10_env': 'PM1.0 (ATM)',
            'pm25_env': 'PM2.5 (ATM)',
            'pm100_env': 'PM10.0 (ATM)',
            'pm10_standard': 'PM1.0 (CF=1)',
            'pm25_standard': 'PM2.5 (CF=1)',
            'pm100_standard': 'PM10.0 (CF=1)',
            'particles_03um': '0.3um',
            'particles_05um': '0.5um',
            'particles_100um': '1.0um',
            'particles_10um': '2.5um',
            'particles_25um': '5.0um',
            'particles_50um': '10.0um',
        }

        for data in entry.payload:
            for attr, key in attr_map.items():
                if key in data:
                    setattr(entry, attr, data[key])

        entry.timestamp = api.parse_datetime(entry.payload[0].get('created_at'))
        entry.position = self.position
        entry.location = self.location

        return super().process_entry(entry)
