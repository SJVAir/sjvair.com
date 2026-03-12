from django.db import models
from django.utils.translation import gettext_lazy as _

from django_smalluuid.models import SmallUUIDField, uuid_default

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
    processor = models.CharField(_('processor'), max_length=100, blank=True, default='', db_index=True)

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

    is_complete = models.BooleanField(
        _('is complete'),
        default=False,
        help_text=_('True if count >= 80% of expected_count.'),
    )

    class Meta:
        abstract = True
        indexes = [
            models.Index(fields=['timestamp', 'resolution', 'entry_type']),
        ]


class MonitorSummary(BaseSummary):
    monitor = models.ForeignKey(
        Monitor,
        on_delete=models.CASCADE,
        related_name='summaries',
    )

    class Meta(BaseSummary.Meta):
        unique_together = ('monitor', 'entry_type', 'processor', 'resolution', 'timestamp')


class RegionSummary(BaseSummary):
    region = models.ForeignKey(
        Region,
        on_delete=models.CASCADE,
        related_name='summaries',
    )
    station_count = models.PositiveIntegerField(_('station count'))

    class Meta(BaseSummary.Meta):
        unique_together = ('region', 'entry_type', 'processor', 'resolution', 'timestamp')
