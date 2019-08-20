from decimal import Decimal

from django.contrib.gis.db import models
from django.contrib.postgres.fields import JSONField

from django_smalluuid.models import SmallUUIDField, uuid_default
from model_utils import Choices
from resticus.encoders import JSONEncoder

from camp.utils.validators import JSONSchemaValidator

from .schemas import PM2_SCHEMA, PAYLOAD_SCHEMA
from .querysets import SensorQuerySet, SensorDataQuerySet


class Sensor(models.Model):
    PLACEMENT = Choices('indoors', 'outdoors')

    id = SmallUUIDField(
        default=uuid_default(),
        primary_key=True,
        db_index=True,
        editable=False,
        verbose_name='ID'
    )
    name = models.CharField(max_length=250)
    position = models.PointField()
    placement = models.CharField(
        max_length=10,
        choices=PLACEMENT,
        default=PLACEMENT.outdoor
    )

    objects = SensorQuerySet.as_manager()

    def __str__(self):
        return self.name


class SensorData(models.Model):
    id = SmallUUIDField(
        default=uuid_default(),
        primary_key=True,
        db_index=True,
        editable=False,
        verbose_name='ID'
    )
    timestamp = models.DateTimeField(auto_now_add=True)
    sensor = models.ForeignKey('sensors.Sensor', related_name='data',
        on_delete=models.CASCADE)
    position = models.PointField()
    placement = models.CharField(
        max_length=10,
        choices=Sensor.PLACEMENT,
        default=Sensor.PLACEMENT.outdoor
    )

    payload = JSONField(encoder=JSONEncoder, validators=[JSONSchemaValidator(PAYLOAD_SCHEMA)])
    is_processed = models.BooleanField(default=False)

    # BME280
    celcius = models.DecimalField(max_digits=4, decimal_places=1, null=True)
    humidity = models.DecimalField(max_digits=4, decimal_places=1, null=True)
    pressure = models.models.DecimalField(max_digits=5, decimal_places=2, null=True)
    altitude = models.models.DecimalField(max_digits=5, decimal_places=2, null=True)

    # PMS5003
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

    def get_fahrenheit(self):
        if self.celcius:
            return (self.celcius * (Decimal(9) / Decimal(5))) + 32

    def set_fahrenheit(self, value):
        self.celcius = (value - 32) * (Decimal(5) / Decimal(9))

    fahrenheit = property(get_fahrenheit, set_fahrenheit)

    def process(self):
        # TODO: What sort of post-processing do we need to do?
        self.celcius = self.payload['celcius']
        self.humidity = self.payload['humidity']
        self.pressure = self.payload['pressure']
        self.pm2_a = self.payload['pm2']['a']
        self.pm2_b = self.payload['pm2']['b']
        self.is_processed = True
