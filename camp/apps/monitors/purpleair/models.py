import time

from datetime import timedelta

from django.contrib.gis.db import models
from django.contrib.gis.geos import Point
from django.contrib.postgres.fields import JSONField
from django.utils.functional import cached_property

from resticus.encoders import JSONEncoder

from camp.apps.monitors.models import Monitor, Entry
from camp.apps.monitors.purpleair.api import purpleair_api
from camp.utils.datetime import parse_datetime


class PurpleAir(Monitor):
    SENSORS = ['a', 'b']

    data = JSONField(default=dict, encoder=JSONEncoder)

    @cached_property
    def purple_id(self):
        return self.data['sensor_index']

    @cached_property
    def thingspeak_key(self):
        return self.data['primary_key_a']

    @cached_property
    def channels(self):
        return purpleair_api.get_channels(self.data)

    def get_feeds(self, **options):
        return {
            'a': purpleair_api.get_feeds(self.channels['a'], **options),
            'b': purpleair_api.get_feeds(self.channels['b'], **options)
        }

    def update_data(self, device_data=None, retries=3):
        if device_data is None:
            device_data = purpleair_api.get_monitor(self.purple_id, self.thingspeak_key)

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
                timestamp=payload[0]['created_at'],
            )
        except Entry.DoesNotExist:
            return super().create_entry(payload, sensor=sensor)

    def copy_fields(self, entry):
        '''
            Copy certain envionment fields to both channels
            so that they each have record of the collected data
        '''
        field_list = ['celcius', 'fahrenheit', 'humidity', 'pressure']
        queryset = Entry.objects.filter(
            monitor_id=entry.monitor_id,
            timestamp__range=(
                entry.timestamp - timedelta(minutes=1),
                entry.timestamp + timedelta(minutes=1),
            )
        ).exclude(sensor=entry.sensor)
        for sibling in queryset:
            sibling_updated = False
            for field in field_list:
                if getattr(entry, field) is not None and getattr(sibling, field) is None:
                    sibling_updated = True
                    setattr(sibling, field, getattr(entry, field))
                if getattr(sibling, field) is not None and getattr(entry, field) is None:
                    setattr(entry, field, getattr(sibling, field))
            if sibling_updated:
                sibling.save()
        return entry

    def process_entry(self, entry):
        attr_map = {
            'fahrenheit': 'Temperature',
            'humidity': 'Humidity',
            'pressure': 'Pressure',
            'pm10': 'PM1.0 (ATM)',
            'pm25': 'PM2.5 (ATM)',
            'pm100': 'PM10.0 (ATM)',
            'particles_03um': '0.3um',
            'particles_05um': '0.5um',
            'particles_10um': '1.0um',
            'particles_25um': '2.5um',
            'particles_50um': '5.0um',
            'particles_100um': '10.0um',
        }

        for data in entry.payload:
            for attr, key in attr_map.items():
                if key in data:
                    setattr(entry, attr, data[key])

        entry.timestamp = parse_datetime(entry.payload[0].get('created_at'))
        entry = self.copy_fields(entry)
        return super().process_entry(entry)
