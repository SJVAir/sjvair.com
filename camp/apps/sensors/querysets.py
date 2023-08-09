import types

from datetime import timedelta

from django.db.models.fields.json import KeyTextTransform
from django.db import models
from django.db.models import Avg, Q
from django.db.models.functions import Cast
from django.utils import timezone


def pm_avg(key, field, cutoff):
    return Avg(
        Cast(
            KeyTextTransform(key, field),
            models.IntegerField()
        ),
        filter=Q(
            data__is_processed=True,
            data__timestamp__gte=cutoff
        )
    )


class SensorQuerySet(models.QuerySet):
    @classmethod
    def as_manager(cls):
        def get_queryset(self):
            # Average the last several minutes
            # of PM2 data for AQI calculations.
            cutoff = timezone.now() - timedelta(minutes=15)
            return SensorQuerySet(self.model, using=self._db).annotate(
                pm25_a_avg=pm_avg('pm25_env', 'data__pm2_a', cutoff),
                pm25_b_avg=pm_avg('pm25_env', 'data__pm2_b', cutoff),
                pm100_a_avg=pm_avg('pm100_env', 'data__pm2_a', cutoff),
                pm100_b_avg=pm_avg('pm100_env', 'data__pm2_b', cutoff),
            )

        manager = super().as_manager()
        manager.get_queryset = types.MethodType(get_queryset, manager)
        return manager


class SensorDataQuerySet(models.QuerySet):
    def processed(self):
        return self.filter(processed=True)
