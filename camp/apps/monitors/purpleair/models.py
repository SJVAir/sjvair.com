import time

from django.contrib.gis.db import models
from django.contrib.gis.geos import Point
from django.contrib.postgres.fields import JSONField
from django.utils.functional import cached_property

from resticus.encoders import JSONEncoder

from camp.apps.monitors.models import Monitor, Entry
from camp.apps.monitors.purpleair import api


class PurpleAir(Monitor):
    purple_id = models.IntegerField(unique=True)
    thingspeak_key = models.CharField(max_length=50)
    data = JSONField(default=dict, encoder=JSONEncoder)

    @cached_property
    def channels(self):
        return api.get_channels(self.data)

    def feed(self, **options):
        return api.get_correlated_feed(self.channels, **options)

    def update_info(self, device_data=None, retries=3):
        if device_data is None:
            device_data = api.get_devices(self.purple_id, self.thingspeak_key)
            if device_data is None:
                if retries:
                    time.sleep(5)
                    return self.update_info(retries=retries - 1)
                return

        self.data = device_data
        self.thingspeak_key = self.data[0]['THINGSPEAK_PRIMARY_ID_READ_KEY']
        self.label = self.data[0]['Label']
        self.position = Point(
            float(self.data[0]['Lon']),
            float(self.data[0]['Lat'])
        )
        self.location = self.data[0]['DEVICE_LOCATIONTYPE']

    def create_entry(self, payload):
        try:
            return self.entries.get(
                timestamp=payload[0]['created_at']
            )
        except Entry.DoesNotExist:
            return super().create_entry(payload)

    def process_entry(self, entry):
        attr_maps = ({
            'fahrenheit': 'Temperature',
            'humidity': 'Humidity',
            'pm25_standard': 'PM2.5 (CF=1)',
            'pm10_env': 'PM1.0 (ATM)',
            'pm25_env': 'PM2.5 (ATM)',
            'pm100_env': 'PM10.0 (ATM)',
        }, {
            'pressure': 'Pressure'
        })

        for index, attr_keys in enumerate(attr_maps):
            try:
                for attr, key in attr_keys.items():
                    setattr(entry, attr, entry.payload[index].get(key))
            except IndexError:
                continue

        entry.timestamp = api.parse_datetime(entry.payload[0].get('created_at'))
        entry.position = self.position
        entry.location = self.location
        entry.is_processed = True
        return entry
