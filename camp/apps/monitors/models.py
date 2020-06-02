from datetime import timedelta
from decimal import Decimal

import aqi

from django.contrib.gis.db import models
from django.contrib.postgres.fields import JSONField
from django.utils import timezone

from django_smalluuid.models import SmallUUIDField, uuid_default
from model_utils import Choices
from model_utils.fields import AutoCreatedField, AutoLastModifiedField
from resticus.encoders import JSONEncoder

from camp.utils.validators import JSONSchemaValidator
from camp.utils.managers import InheritanceManager


class Monitor(models.Model):
    LOCATION = Choices('inside', 'outside')
    PAYLOAD_SCHEMA = None

    id = SmallUUIDField(
        default=uuid_default(),
        primary_key=True,
        db_index=True,
        editable=False,
        verbose_name='ID'
    )

    name = models.CharField(max_length=250)
    # nickname = models.CharField(max_length=250)
    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)

    # Where is this sensor setup?
    position = models.PointField(null=True, db_index=True)
    location = models.CharField(max_length=10, choices=LOCATION)

    latest = models.ForeignKey('monitors.Entry',
        related_name='monitor_latest',
        null=True,
        on_delete=models.SET_NULL
    )

    objects = InheritanceManager()

    class Meta:
        ordering = ('name',)

    def __str__(self):
        return self.name

    @property
    def device(self):
        return self.__class__.__name__

    @property
    def is_active(self):
        if self.latest_id is None:
            return False
        now = timezone.now()
        cutoff = timedelta(seconds=60 * 10)
        return (now - self.latest.timestamp) < cutoff

    def create_entry(self, payload):
        return Entry(
            monitor=self,
            payload=payload,
            position=self.position,
            location=self.location,
            is_processed=False,
        )

    def process_entry(self, entry):
        return NotImplemented


class Entry(models.Model):
    id = SmallUUIDField(
        default=uuid_default(),
        primary_key=True,
        db_index=True,
        editable=False,
        verbose_name='ID'
    )
    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)
    monitor = models.ForeignKey('monitors.Monitor', related_name='entries', on_delete=models.CASCADE)

    # Where was the monitor when this entry was logged?
    position = models.PointField(null=True, db_index=True)
    location = models.CharField(max_length=10, choices=Monitor.LOCATION)

    # Has the raw data been calibrated and processed?
    is_processed = models.BooleanField(default=False, db_index=True)

    # Original payload from the device / api
    payload = JSONField(
        encoder=JSONEncoder,
        default=dict
    )

    # Post-processed, calibrated data
    celcius = models.DecimalField(max_digits=4, decimal_places=1, null=True)
    fahrenheit = models.DecimalField(max_digits=4, decimal_places=1, null=True)
    humidity = models.DecimalField(max_digits=4, decimal_places=1, null=True)
    pressure = models.DecimalField(max_digits=6, decimal_places=2, null=True)

    pm100_env = models.DecimalField(max_digits=5, decimal_places=2, null=True)
    pm10_env = models.DecimalField(max_digits=5, decimal_places=2, null=True)
    pm25_env = models.DecimalField(max_digits=5, decimal_places=2, null=True)

    pm100_standard = models.DecimalField(max_digits=5, decimal_places=2, null=True)
    pm10_standard = models.DecimalField(max_digits=5, decimal_places=2, null=True)
    pm25_standard = models.DecimalField(max_digits=5, decimal_places=2, null=True)

    particles_03um = models.DecimalField(max_digits=7, decimal_places=2, null=True)
    particles_05um = models.DecimalField(max_digits=7, decimal_places=2, null=True)
    particles_100um = models.DecimalField(max_digits=7, decimal_places=2, null=True)
    particles_10um = models.DecimalField(max_digits=7, decimal_places=2, null=True)
    particles_25um = models.DecimalField(max_digits=7, decimal_places=2, null=True)
    particles_50um = models.DecimalField(max_digits=7, decimal_places=2, null=True)

    epa_pm25_aqi = models.IntegerField(null=True)
    epa_pm100_aqi = models.IntegerField(null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['monitor', 'timestamp'], name='unique_entry')
        ]
        ordering = ('-timestamp',)


    def save(self, *args, **kwargs):
        # Temperature adjustments
        if self.fahrenheit is None and self.celcius is not None:
            self.fahrenheit = (Decimal(self.celcius) * (Decimal(9) / Decimal(5))) + 32
        if self.celcius is None and self.fahrenheit is not None:
            self.celcius = (Decimal(self.fahrenheit) - 32) * (Decimal(5) / Decimal(9))

        return super().save(*args, **kwargs)
