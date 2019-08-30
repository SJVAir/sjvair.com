import statistics

from datetime import timedelta
from decimal import Decimal

import aqi

from django.contrib.gis.db import models
from django.contrib.postgres.fields import JSONField
from django.utils import timezone

from django_smalluuid.models import SmallUUIDField, uuid_default
from model_utils import Choices
from resticus.encoders import JSONEncoder

from camp.utils.validators import JSONSchemaValidator

from .schemas import PM2_SCHEMA, PAYLOAD_SCHEMA
from .querysets import SensorQuerySet, SensorDataQuerySet


class Sensor(models.Model):
    LOCATION = Choices('inside', 'outside')

    id = SmallUUIDField(
        default=uuid_default(),
        primary_key=True,
        db_index=True,
        editable=False,
        verbose_name='ID'
    )
    name = models.CharField(max_length=250)

    # Where is this sensor setup?
    position = models.PointField(null=True)
    location = models.CharField(max_length=10, choices=LOCATION)

    # Maintain a relation to the latest sensor reading
    latest = models.ForeignKey('sensors.SensorData', related_name='sensor_latest', null=True, on_delete=models.SET_NULL)

    objects = SensorQuerySet.as_manager()

    def __str__(self):
        return self.name

    @property
    def is_active(self):
        if self.latest_id is None:
            return False
        now = timezone.now()
        cutoff = timedelta(seconds=60 * 20)
        return now - self.latest.timestamp < cutoff

    @property
    def epa_pm25_aqi(self):
        # CONSIDER: Instead of averaging the two
        # sensors, should we just pick one?
        try:
            pm25 = statistics.mean(filter(bool, (self.pm25_a_avg, self.pm25_b_avg)))
            return aqi.to_iaqi(aqi.POLLUTANT_PM25, pm25, algo=aqi.ALGO_EPA)
        except statistics.StatisticsError:
            pass

    @property
    def epa_pm100_aqi(self):
        # CONSIDER: Instead of averaging the two
        # sensors, should we just pick one?
        try:
            pm100 = statistics.mean(filter(bool, (self.pm100_a_avg, self.pm100_b_avg)))
            return aqi.to_iaqi(aqi.POLLUTANT_PM10, pm100, algo=aqi.ALGO_EPA)
        except statistics.StatisticsError:
            pass

    def update_latest(self, commit=True):
        try:
            self.latest = (self.data
                .filter(is_processed=True)
                .latest('timestamp'))
        except SensorData.DoesNotExist:
            return
        else:
            if commit:
                self.save()


class SensorData(models.Model):
    id = SmallUUIDField(
        default=uuid_default(),
        primary_key=True,
        db_index=True,
        editable=False,
        verbose_name='ID'
    )
    timestamp = models.DateTimeField(auto_now_add=True)
    sensor = models.ForeignKey('sensors.Sensor', related_name='data', on_delete=models.CASCADE)
    position = models.PointField(null=True)
    location = models.CharField(max_length=10, choices=Sensor.LOCATION)
    altitude = models.DecimalField(max_digits=5, decimal_places=2, null=True)

    payload = JSONField(
        encoder=JSONEncoder,
        validators=[JSONSchemaValidator(PAYLOAD_SCHEMA)],
        default=dict
    )
    is_processed = models.BooleanField(default=False)

    # BME280
    celcius = models.DecimalField(max_digits=4, decimal_places=1, null=True)
    fahrenheit = models.DecimalField(max_digits=4, decimal_places=1, null=True)
    humidity = models.DecimalField(max_digits=4, decimal_places=1, null=True)
    pressure = models.DecimalField(max_digits=6, decimal_places=2, null=True)

    # PMS5003 A/B
    pm2_a = JSONField(null=True, encoder=JSONEncoder, validators=[
        JSONSchemaValidator(PM2_SCHEMA)
    ])
    pm2_b = JSONField(null=True, encoder=JSONEncoder, validators=[
        JSONSchemaValidator(PM2_SCHEMA)
    ])

    objects = SensorDataQuerySet.as_manager()

    class Meta:
        ordering = ('-timestamp',)

    def __str__(self):
        return f'timestamp={self.timestamp} position={self.position}'

    def save(self, *args, **kwargs):
        # Temperature adjustments
        if self.fahrenheit is None and self.celcius is not None:
            self.fahrenheit = (Decimal(self.celcius) * (Decimal(9) / Decimal(5))) + 32
        if self.celcius is None and self.fahrenheit is not None:
            self.celcius = (Decimal(value) - 32) * (Decimal(5) / Decimal(9))

        return super().save(*args, **kwargs)

    def process_pm2(pm2):
        pm2['pm2_aqi'] = aqi.to_iaqi(aqi.POLLUTANT_PM25, pm2['pm25_standard'])
        pm2['pm100_aqi'] = aqi.to_iaqi(aqi.POLLUTANT_PM25, pm2['pm100_standard'])
        return pm2

    def process(self, commit=True):
        # TODO: What sort of post-processing do we need to do?
        self.celcius = self.payload['celcius']
        self.humidity = self.payload['humidity']
        self.pressure = self.payload['pressure']
        self.pm2_a = self.payload['pm2_a']
        self.pm2_b = self.payload['pm2_b']
        self.is_processed = True

        if commit:
            self.save()
