from django.contrib.gis.db import models
from django.contrib.postgres.fields import JSONField

from django_smalluuid.models import SmallUUIDField, uuid_default

from aqm.utils.validators import JSONSchemaValidator

from .schemas import PM2_SCHEMA, PAYLOAD_SCHEMA
from .querysets import SensorQuerySet, SensorDataQuerySet


class Sensor(models.Model):
    id = SmallUUIDField(
        default=uuid_default(),
        primary_key=True,
        db_index=True,
        editable=False,
        verbose_name='ID'
    )
    name = models.CharField(max_length=250)
    position = models.PointField()

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

    payload = JSONField(validators=[JSONSchemaValidator(PAYLOAD_SCHEMA)])
    is_processed = models.BooleanField(default=False)

    celcius = models.DecimalField(max_digits=4, decimal_places=1, null=True)
    humidity = models.DecimalField(max_digits=4, decimal_places=1, null=True)
    # Air pressure? Altitude?

    pm2 = JSONField(null=True, validators=[
        JSONSchemaValidator(PAYLOAD_SCHEMA['properties']['pm2'])
    ])

    objects = SensorDataQuerySet.as_manager()

    def __str__(self):
        return f'<SensorData timestamp={self.timestamp} position={self.position}>'

    def get_fahrenheit(self):
        return (self.celcius * (9. / 5.)) + 32

    def set_fahrenheit(self, value):
        self.celcius = (value - 32) * (5. / 9.)

    fahrenheit = property(get_fahrenheit, set_fahrenheit)

    def process(self):
        self.celcius = self.payload['celcius']
        self.humidity = self.payload['humidity']
        self.pm2_a = self.payload['pm2']['a']
        self.pm2_b = self.payload['pm2']['b']
        self.is_processed = True
