from django.db import models

# Create your models here.
from django.db import models
from django.utils import timezone
from django.utils.functional import lazy

from django_smalluuid.models import SmallUUIDField, uuid_default
from geopy.distance import distance as geopy_distance
from model_utils.models import TimeStampedModel

from camp.apps.monitors.models import Monitor


class SensorAnalysis(TimeStampedModel):
    id = SmallUUIDField(
        default=uuid_default(),
        primary_key=True,
        db_index=True,
        editable=False,
        verbose_name='ID'
    )

    monitor = models.ForeignKey('monitors.Monitor',
        related_name='sensor_analysis',
        on_delete=models.CASCADE
    )

    r2 = models.FloatField()
    intercept = models.FloatField()
    coef = models.FloatField()
    start_date = models.DateTimeField()
    end_date = models.DateTimeField()

    @property
    def is_under_threshold(self):
        return self.r2 < 0.9

    def save_as_current(self):
        self.save()
        self.monitor.current_health = self
        self.monitor.save()

    def __str__(self):
        return "{:.2f}".format(self.r2)
