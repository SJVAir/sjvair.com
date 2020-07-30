from datetime import timedelta
from decimal import Decimal

import aqi

from django.contrib.gis.db import models
from django.db.models import Avg
from django.db.models.functions import Least
from django.contrib.postgres.fields import JSONField
from django.utils import timezone

from django_smalluuid.models import SmallUUIDField, uuid_default
from model_utils import Choices
from model_utils.fields import AutoCreatedField, AutoLastModifiedField
from py_expression_eval import Parser as ExpressionParser
from resticus.encoders import JSONEncoder

from camp.utils.validators import JSONSchemaValidator
from camp.utils.managers import InheritanceManager


class Monitor(models.Model):
    LOCATION = Choices('inside', 'outside')
    PAYLOAD_SCHEMA = None
    DEFAULT_SENSOR = None

    id = SmallUUIDField(
        default=uuid_default(),
        primary_key=True,
        db_index=True,
        editable=False,
        verbose_name='ID'
    )

    name = models.CharField(max_length=250)
    created = models.DateTimeField(auto_now_add=True)
    modified = models.DateTimeField(auto_now=True)
    is_hidden = models.BooleanField(default=False)

    # Where is this sensor setup?
    position = models.PointField(null=True, db_index=True)
    location = models.CharField(max_length=10, choices=LOCATION)

    latest = models.ForeignKey('monitors.Entry',
        related_name='monitor_latest',
        null=True,
        on_delete=models.SET_NULL
    )

    pm25_calibration_formula = models.CharField(max_length=255, blank=True, default='')

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

    def create_entry(self, payload, sensor=None):
        return Entry(
            monitor=self,
            payload=payload,
            sensor=sensor or '',
            position=self.position,
            location=self.location,
            is_processed=False,
        )

    def process_entry(self, entry):
        entry.calibrate_pm25(self.pm25_calibration_formula)
        entry.calculate_aqi()
        entry.calculate_average('pm25_env', 'pm25_avg_15', 15)
        entry.calculate_average('pm25_env', 'pm25_avg_60', 60)
        entry.is_processed = True
        return entry


class Entry(models.Model):
    ENVIRONMENT = [
        'celcius', 'fahrenheit', 'humidity', 'pressure',
        'pm10_env', 'pm25_env', 'pm100_env',
        'pm10_standard', 'pm25_standard', 'pm100_standard',
        'particles_03um', 'particles_05um', 'particles_10um',
        'particles_25um', 'particles_50um', 'particles_100um',
    ]

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
    sensor = models.CharField(max_length=50, blank=True, default='', db_index=True)

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

    pm25_calibration_formula = models.CharField(max_length=255, blank=True, default='')

    # Post-processed, calibrated data
    celcius = models.DecimalField(max_digits=4, decimal_places=1, null=True)
    fahrenheit = models.DecimalField(max_digits=4, decimal_places=1, null=True)
    humidity = models.DecimalField(max_digits=4, decimal_places=1, null=True)
    pressure = models.DecimalField(max_digits=6, decimal_places=2, null=True)

    pm10_env = models.DecimalField(max_digits=6, decimal_places=2, null=True)
    pm25_env = models.DecimalField(max_digits=6, decimal_places=2, null=True)
    pm100_env = models.DecimalField(max_digits=6, decimal_places=2, null=True)

    pm10_standard = models.DecimalField(max_digits=6, decimal_places=2, null=True)
    pm25_standard = models.DecimalField(max_digits=6, decimal_places=2, null=True)
    pm100_standard = models.DecimalField(max_digits=6, decimal_places=2, null=True)

    pm25_avg_15 = models.DecimalField(max_digits=6, decimal_places=2, null=True)
    pm25_avg_60 = models.DecimalField(max_digits=6, decimal_places=2, null=True)

    pm25_aqi = models.IntegerField(null=True)
    pm100_aqi = models.IntegerField(null=True)

    particles_03um = models.DecimalField(max_digits=7, decimal_places=2, null=True)
    particles_05um = models.DecimalField(max_digits=7, decimal_places=2, null=True)
    particles_10um = models.DecimalField(max_digits=7, decimal_places=2, null=True)
    particles_25um = models.DecimalField(max_digits=7, decimal_places=2, null=True)
    particles_50um = models.DecimalField(max_digits=7, decimal_places=2, null=True)
    particles_100um = models.DecimalField(max_digits=7, decimal_places=2, null=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['monitor', 'timestamp'], name='unique_entry')
        ]
        ordering = ('-timestamp',)

    def get_calibration_context(self):
        return {
            field: float(getattr(self, field, None) or 0)
            for field in self.ENVIRONMENT
        }

    def calculate_average(self, field, attr, minutes):
        values = list(Entry.objects
            .filter(
                monitor=self.monitor,
                sensor=self.sensor,
                timestamp__range=(
                    self.timestamp - timedelta(minutes=minutes),
                    self.timestamp,
                ))
            .exclude(
                pk=self.pk,
                **{f'{field}__isnull': True})
            .values_list(field, flat=True)
        )

        if getattr(self, field):
            values.append(Decimal(getattr(self, field)))

        if values:
            setattr(self, attr, sum(values) / len(values))

    def calculate_aqi(self):
        avg = (Entry.objects
            .filter(
                monitor_id=self.monitor_id,
                sensor=self.sensor,
                timestamp__range=(
                    self.timestamp - timedelta(hours=12),
                    self.timestamp
                ),
                pm25_env__isnull=False,
                pm100_env__isnull=False,
            )
            .aggregate(
                pm25=Least(Avg('pm25_env'), 500),
                pm100=Least(Avg('pm100_env'), 604),
            )
        )

        self.pm25_aqi = aqi.to_iaqi(aqi.POLLUTANT_PM25, avg['pm25'] or 0, algo=aqi.ALGO_EPA)
        self.pm100_aqi = aqi.to_iaqi(aqi.POLLUTANT_PM10, avg['pm100'] or 0, algo=aqi.ALGO_EPA)

    def calibrate_pm25(self, formula):
        if formula:
            parser = ExpressionParser()
            expression = parser.parse(formula)
            context = self.get_calibration_context()

            self.pm25_env = expression.evaluate(context)
            self.pm25_calibration_formula = formula

    def save(self, *args, **kwargs):
        # Temperature adjustments
        if self.fahrenheit is None and self.celcius is not None:
            self.fahrenheit = (Decimal(self.celcius) * (Decimal(9) / Decimal(5))) + 32
        if self.celcius is None and self.fahrenheit is not None:
            self.celcius = (Decimal(self.fahrenheit) - 32) * (Decimal(5) / Decimal(9))

        return super().save(*args, **kwargs)
