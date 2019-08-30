import types

from datetime import timedelta

from django.contrib.postgres.fields.jsonb import KeyTextTransform
from django.db import models
from django.db.models import Avg, Q
from django.db.models.functions import Cast
from django.utils import timezone


class SensorQuerySet(models.QuerySet):
    @classmethod
    def as_manager(cls):
        def get_queryset(self):
            # By default, include the last 24 hours
            # of PM2 data for AQI calculations.
            cutoff = timezone.now() - timedelta(hours=24)
            return SensorQuerySet(self.model, using=self._db).annotate(
                pm25_a_avg=Avg(Cast(KeyTextTransform('pm25_env', 'data__pm2_a'), models.IntegerField()), filter=Q(data__timestamp__gte=cutoff)),
                pm25_b_avg=Avg(Cast(KeyTextTransform('pm25_env', 'data__pm2_b'), models.IntegerField()), filter=Q(data__timestamp__gte=cutoff)),
                pm100_a_avg=Avg(Cast(KeyTextTransform('pm100_env', 'data__pm2_a'), models.IntegerField()), filter=Q(data__timestamp__gte=cutoff)),
                pm100_b_avg=Avg(Cast(KeyTextTransform('pm100_env', 'data__pm2_b'), models.IntegerField()), filter=Q(data__timestamp__gte=cutoff)),
            )

        manager = super().as_manager()
        manager.get_queryset = types.MethodType(get_queryset, manager)
        return manager


class SensorDataQuerySet(models.QuerySet):
    def processed(self):
        return self.filter(processed=True)
