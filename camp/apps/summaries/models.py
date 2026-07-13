from django.db import models
from django.utils.translation import gettext_lazy as _

from django_smalluuid.models import SmallUUIDField, uuid_default
from django_sqids import SqidsField, shuffle_alphabet
from model_utils.models import TimeStampedModel

from camp.apps.entries.fields import EntryTypeField
from camp.apps.monitors.models import Monitor
from camp.apps.regions.models import Region


class BaseSummary(models.Model):
    class Resolution(models.TextChoices):
        HOURLY = 'hour', _('Hourly')
        DAILY = 'day', _('Daily')
        MONTHLY = 'month', _('Monthly')
        QUARTERLY = 'quarter', _('Quarterly')
        SEASONAL = 'season', _('Seasonal')
        YEARLY = 'year', _('Yearly')

    id = SmallUUIDField(
        default=uuid_default(),
        primary_key=True,
        editable=False,
    )

    resolution = models.CharField(_('resolution'), max_length=10, choices=Resolution.choices)
    timestamp = models.DateTimeField(_('timestamp'))
    entry_type = EntryTypeField()

    # Rollup machinery — needed for correct aggregation across time periods
    count = models.PositiveIntegerField(_('count'))
    expected_count = models.PositiveIntegerField(_('expected count'))
    sum_value = models.FloatField(_('sum'))
    sum_of_squares = models.FloatField(_('sum of squares'))
    tdigest = models.JSONField(_('t-digest'))

    # Readable stats
    minimum = models.FloatField(_('minimum'))
    maximum = models.FloatField(_('maximum'))
    mean = models.FloatField(_('mean'))
    stddev = models.FloatField(_('standard deviation'))
    p25 = models.FloatField(_('25th percentile'))
    p75 = models.FloatField(_('75th percentile'))

    class Meta:
        abstract = True
        indexes = [
            models.Index(fields=['timestamp', 'resolution', 'entry_type']),
            models.Index(fields=['resolution', 'timestamp']),
        ]


class MonitorSummary(BaseSummary):
    monitor = models.ForeignKey(
        Monitor,
        on_delete=models.CASCADE,
        related_name='summaries',
    )
    processor = models.CharField(_('processor'), max_length=100, blank=True, default='', db_index=True)
    is_complete = models.BooleanField(_('is complete'), default=False)

    class Meta(BaseSummary.Meta):
        unique_together = ('monitor', 'entry_type', 'processor', 'resolution', 'timestamp')


class RegionSummary(BaseSummary):
    region = models.ForeignKey(
        Region,
        on_delete=models.CASCADE,
        related_name='summaries',
    )
    station_count = models.PositiveIntegerField(_('station count'))
    # Exact float total weight — used as variance denominator so rollup stddev is
    # correct even when monitor health scores produce fractional weights. `count`
    # stores int(round(weight)) for API display; `weight` carries the precise value.
    weight = models.FloatField(_('weight'), default=0.0)

    class Meta(BaseSummary.Meta):
        unique_together = ('region', 'entry_type', 'resolution', 'timestamp')


class SummaryBackfillJob(TimeStampedModel):
    class State(models.TextChoices):
        RUNNING = 'running', _('Running')
        PAUSED = 'paused', _('Paused')
        DONE = 'done', _('Done')
        FAILED = 'failed', _('Failed')

    class Phase(models.TextChoices):
        IDLE = 'idle', _('Idle')
        MONITORS = 'monitors', _('Monitors')
        REGIONS = 'regions', _('Regions')

    sqid = SqidsField(alphabet=shuffle_alphabet('summaries.SummaryBackfillJob'))

    state = models.CharField(_('state'), max_length=10, choices=State.choices, default=State.RUNNING)
    phase = models.CharField(_('phase'), max_length=10, choices=Phase.choices, default=Phase.IDLE)

    cursor = models.DateTimeField(_('cursor'))
    chunk_start = models.DateTimeField(_('chunk start'), null=True, blank=True)
    range_start = models.DateTimeField(_('range start'))
    range_end = models.DateTimeField(_('range end'))

    pending_tasks = models.PositiveIntegerField(_('pending tasks'), default=0)
    batch_id = models.PositiveIntegerField(_('batch id'), default=0)
    phase_started_at = models.DateTimeField(_('phase started at'), null=True, blank=True)
    locked_at = models.DateTimeField(_('locked at'), null=True, blank=True)

    consecutive_failures = models.PositiveSmallIntegerField(_('consecutive failures'), default=0)
    last_error = models.TextField(_('last error'), blank=True, default='')

    def __str__(self):
        return f'{self.state} ({self.phase}) @ {self.cursor:%Y-%m-%d}'
