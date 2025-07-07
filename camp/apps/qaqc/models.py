from datetime import timedelta

from django.db import models
from django.utils.functional import cached_property

from django_smalluuid.models import SmallUUIDField, uuid_default
from model_utils.models import TimeStampedModel

from camp.apps.qaqc.evaluator import HealthCheckEvaluator
from camp.apps.qaqc.managers import HealthCheckManager


class HealthCheck(TimeStampedModel):
    id = SmallUUIDField(
        default=uuid_default(),
        primary_key=True,
        db_index=True,
        editable=False,
        verbose_name='ID'
    )

    monitor = models.ForeignKey('monitors.Monitor',
        related_name='health_checks',
        on_delete=models.CASCADE
    )
    hour = models.DateTimeField()

    score = models.PositiveSmallIntegerField()
    variance = models.FloatField(null=True, blank=True)
    correlation = models.FloatField(null=True, blank=True)

    objects = HealthCheckManager()

    class Meta:
        indexes = [models.Index(fields=['monitor', 'hour'])]
        ordering = ['-hour', 'monitor']
        unique_together = ('monitor', 'hour')

    @property
    def grade(self) -> str:
        return {2: 'A', 1: 'B', 0: 'F'}.get(self.score, 'F')

    @cached_property
    def evaluator(self):
        return HealthCheckEvaluator(self.monitor, self.hour)

    def evaluate(self):
        result = self.evaluator.evaluate()
        self.score = result.score
        self.variance = result.variance
        self.correlation = result.correlation

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.monitor.health or self.monitor.health.hour < self.hour:
            self.monitor.health_id = self.pk
            self.monitor.save(update_fields=['health_id'])
