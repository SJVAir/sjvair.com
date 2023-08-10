from django.db import models

# Create your models here.
from django.db import models
from django.utils import timezone
from django.utils.functional import lazy

from django_smalluuid.models import SmallUUIDField, uuid_default
from geopy.distance import distance as geopy_distance
from model_utils.models import TimeStampedModel

from camp.apps.monitors.models import Monitor
from camp.apps.monitors.validators import validate_formula
from camp.apps.calibrations.linreg import LinearRegressions
from camp.apps.calibrations.querysets import CalibratorQuerySet


class SensorAnalysis(TimeStampedModel):
    id = SmallUUIDField(
        default=uuid_default(),
        primary_key=True,
        db_index=True,
        editable=False,
        verbose_name='ID'
    )

    monitor = models.ForeignKey('monitors.Monitor', on_delete=models.CASCADE)

    r2 = models.FloatField(required=True)
    intercept = models.FloatField(required=True)
    coef = models.FloatField(required=True)
    start_date = models.DateTimeField(required=True)
    end_date = models.DateTimeField(required=True)

