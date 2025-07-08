from datetime import timedelta

from django.db import models
from django.utils.functional import cached_property

from django_smalluuid.models import SmallUUIDField, uuid_default
from model_utils.models import TimeStampedModel

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

    # Comparison stats between the A|1/B|2 channels
    correlation = models.FloatField(blank=True, null=True)
    rpd_means = models.FloatField(blank=True, null=True)
    rpd_pairwise = models.FloatField(blank=True, null=True)
    rmse = models.FloatField(blank=True, null=True)

    # Summary stats for A|1 channel
    min_a = models.FloatField(blank=True, null=True)
    max_a = models.FloatField(blank=True, null=True)
    count_a = models.IntegerField(blank=True, null=True)
    mean_a = models.FloatField(blank=True, null=True)
    stdev_a = models.FloatField(blank=True, null=True)
    variance_a = models.FloatField(blank=True, null=True)
    mad_a = models.FloatField(blank=True, null=True)
    range_a = models.FloatField(blank=True, null=True)
    flatline_a = models.FloatField(blank=True, null=True)

    # Summary stats for the B|2 channel
    min_b = models.FloatField(blank=True, null=True)
    max_b = models.FloatField(blank=True, null=True)
    count_b = models.IntegerField(blank=True, null=True)
    mean_b = models.FloatField(blank=True, null=True)
    stdev_b = models.FloatField(blank=True, null=True)
    variance_b = models.FloatField(blank=True, null=True)
    mad_b = models.FloatField(blank=True, null=True)
    range_b = models.FloatField(blank=True, null=True)
    flatline_b = models.FloatField(blank=True, null=True)

    # Sanity checks for the A|1 channel
    sanity_completeness_a = models.BooleanField(null=True)
    sanity_max_a = models.BooleanField(null=True)
    sanity_flatline_a = models.BooleanField(null=True)

    # Sanity checks for the B|2 channel
    sanity_completeness_b = models.BooleanField(null=True)
    sanity_max_b = models.BooleanField(null=True)
    sanity_flatline_b = models.BooleanField(null=True)

    objects = HealthCheckManager()

    class Meta:
        indexes = [models.Index(fields=['monitor', 'hour'])]
        ordering = ['-hour', 'monitor']
        unique_together = ('monitor', 'hour')

    def __str__(self):
        return str(self.pk)

    @property
    def grade(self) -> str:
        return {2: 'A', 1: 'B', 0: 'F'}.get(self.score, 'F')

    @cached_property
    def evaluator(self):
        from camp.apps.qaqc.evaluator import HealthCheckEvaluator
        return HealthCheckEvaluator(self.monitor, self.hour)

    @property
    def completeness_a(self):
        return self.calculate_completeness(self.count_a)

    @property
    def completeness_b(self):
        return self.calculate_completeness(self.count_b)

    def calculate_completeness(self, count):
        expected = self.monitor.expected_hourly_entries
        if count is not None:
            return (count / expected) * 100

    def _set_attrs(self, data):
        for key, value in data.items():
            if hasattr(self, key):
                setattr(self, key, value)

    def evaluate(self):
        results = self.evaluator.evaluate()
        self.score = results.score

        if results.summary:
            self._set_attrs(results.summary.as_dict(flat=True))

        if results.sanity_a:
            self._set_attrs(results.sanity_a.as_dict('a'))

        if results.sanity_b:
            self._set_attrs(results.sanity_b.as_dict('b'))

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.monitor.health or self.monitor.health.hour < self.hour:
            self.monitor.health_id = self.pk
            self.monitor.save(update_fields=['health_id'])
