from django.contrib.gis.db import models
from django.contrib.postgres.fields import JSONField

from django_smalluuid.models import SmallUUIDField, uuid_default

from aqm.apps.sensors.schemas import PM2_SCHEMA, PAYLOAD_SCHEMA
from aqm.utils.validators import JSONSchemaValidator


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


class Reading(models.Model):
    id = SmallUUIDField(
        default=uuid_default(),
        primary_key=True,
        db_index=True,
        editable=False,
        verbose_name='ID'
    )
    timestamp = models.DateTimeField(auto_now_add=True)
    sensor = models.ForeignKey('sensors.Sensor', related_name='readings', on_delete=models.CASCADE)
    position = models.PointField()

    payload = JSONField(validators=[JSONSchemaValidator(PAYLOAD_SCHEMA)])
    is_processed = models.BooleanField(default=False)

    celcius = models.DecimalField(max_digits=4, decimal_places=1)
    humidity = models.DecimalField(max_digits=4, decimal_places=1)
    # Air pressure? Altitude?

    pm2_a = JSONField(validators=[JSONSchemaValidator(PM2_SCHEMA)])
    pm2_b = JSONField(validators=[JSONSchemaValidator(PM2_SCHEMA)])


    def get_fahrenheit(self):
        return (self.celcius * (9. / 5.)) + 32

    def set_fahrenheit(self, value):
        self.celcius = (value - 32) * (5. / 9.)

    fahrenheit = property(get_fahrenheit, set_fahrenheit)
