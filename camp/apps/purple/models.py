import time

from decimal import Decimal

from django.contrib.gis.db import models
from django.contrib.gis.geos import Point
from django.contrib.postgres.fields import JSONField
from django.contrib.postgres.indexes import GinIndex
from django.utils.functional import cached_property

from django_smalluuid.models import SmallUUIDField, uuid_default
from model_utils import Choices
from resticus.encoders import JSONEncoder

from camp.utils.validators import JSONSchemaValidator

from . import api
from .schemas import PM2_SCHEMA

pm2_keymap = (
    ('pm25_standard', 'PM2.5 (CF=1)'),
    ('pm10_env', 'PM1.0 (ATM)'),
    ('pm25_env', 'PM2.5 (ATM)'),
    ('pm100_env', 'PM10.0 (ATM)'),
)


class PurpleAir(models.Model):
    LOCATION = Choices('inside', 'outside')

    id = SmallUUIDField(
        default=uuid_default(),
        primary_key=True,
        db_index=True,
        editable=False,
        verbose_name='ID'
    )

    purple_id = models.IntegerField(unique=True)
    label = models.CharField(max_length=250)
    position = models.PointField(null=True)
    location = models.CharField(max_length=10, choices=LOCATION)

    data = JSONField(
        encoder=JSONEncoder,
        default=list
    )

    latest = models.ForeignKey('purple.Entry',
        related_name='device_latest',
        null=True,
        on_delete=models.SET_NULL
    )

    class Meta:
        ordering = ['label']

    def __str__(self):
        return self.label

    @property
    def thingspeak_key(self):
        try:
            return self.data[0]['THINGSPEAK_PRIMARY_ID_READ_KEY']
        except (IndexError, KeyError):
            return None


    def update_device_data(self, retries=3):
        device_data = api.get_devices(self.purple_id, self.thingspeak_key)
        if device_data is None:
            if retries:
                time.sleep(5)
                return self.update_device_data(retries=retries - 1)
            return

        self.data = device_data
        self.label = self.data[0]['Label']
        self.position = Point(
            float(self.data[0]['Lon']),
            float(self.data[0]['Lat'])
        )
        self.location = self.data[0]['DEVICE_LOCATIONTYPE']

    @cached_property
    def channels(self):
        return api.get_channels(self.data)

    def feed(self, **options):
        return api.get_correlated_feed(self.channels, **options)

    def add_entry(self, items):
        try:
            entry = self.entries.get(
                timestamp=items[0]['created_at']
            )
        except Entry.DoesNotExist:
            entry = Entry(device=self)

        entry.timestamp = items[0]['created_at']
        entry.position = self.position
        entry.location = self.location

        entry.data = items
        entry.fahrenheit = items[0].get('Temperature')
        entry.humidity = items[0].get('Humidity')

        entry.pm2_a = {ck: items[0].get(pk) for ck, pk in pm2_keymap}

        if len(items) == 2:
            entry.pressure = items[1].get('Pressure')
            entry.pm2_b = {ck: items[1].get(pk) for ck, pk in pm2_keymap}

        entry.save()
        return entry


class Entry(models.Model):
    id = SmallUUIDField(
        default=uuid_default(),
        primary_key=True,
        db_index=True,
        editable=False,
        verbose_name='ID'
    )
    device = models.ForeignKey('purple.PurpleAir',
        related_name='entries',
        on_delete=models.CASCADE
    )
    timestamp = models.DateTimeField(db_index=True)
    position = models.PointField(null=True)
    location = models.CharField(max_length=10, choices=PurpleAir.LOCATION)

    data = JSONField(
        encoder=JSONEncoder,
        default=list
    )

    celcius = models.DecimalField(max_digits=4, decimal_places=1, null=True)
    fahrenheit = models.DecimalField(max_digits=4, decimal_places=1, null=True)
    humidity = models.DecimalField(max_digits=4, decimal_places=1, null=True)
    pressure = models.DecimalField(max_digits=6, decimal_places=2, null=True)

    pm2_a = JSONField(null=True, encoder=JSONEncoder, validators=[
        JSONSchemaValidator(PM2_SCHEMA)
    ])
    pm2_b = JSONField(null=True, encoder=JSONEncoder, validators=[
        JSONSchemaValidator(PM2_SCHEMA)
    ])

    class Meta:
        indexes = [
            GinIndex(fields=['data'])
        ]

    def save(self, *args, **kwargs):
        # Temperature adjustments
        if self.fahrenheit is None and self.celcius is not None:
            self.fahrenheit = (Decimal(self.celcius) * (Decimal(9) / Decimal(5))) + 32
        if self.celcius is None and self.fahrenheit is not None:
            self.celcius = (Decimal(self.fahrenheit) - 32) * (Decimal(5) / Decimal(9))

        return super().save(*args, **kwargs)

