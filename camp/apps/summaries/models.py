# camp/apps/summaries/models.py

from django.db import models
from django.utils import timezone
from fastdigest import TDigest
from camp.apps.entries.fields import EntryTypeField
from camp.apps.monitors.models import Monitor
from camp.apps.regions.models import Region

from django_sqids import SqidsField, shuffle_alphabet

from django.contrib.postgres.fields import JSONField  # or models.JSONField for Django 3.1+
from django.utils.translation import gettext_lazy as _


class BaseSummary(models.Model):
    """
    Abstract base class for monitor and region summaries.
    """

    class Resolution(models.TextChoices):
        HOURLY = 'hour', 'Hourly'
        DAILY = 'day', 'Daily'
        WEEKLY = 'week', 'Weekly'
        MONTHLY = 'month', 'Monthly'
        QUARTERLY = 'quarter', 'Quarterly'
        SEASONAL = 'season', 'Seasonal'
        SEMIANNUAL = 'semiannual', 'Semiannual'
        YEARLY = 'year', 'Yearly'

    class QCFlag(models.TextChoices):
        NONE = '', 'No issues'
        FLATLINE = 'FLATLINE', 'Flatline detected'
        SPIKEY = 'SPIKEY', 'Excessive spikes'
        DROPOUT = 'DROPOUT', 'Intermittent data loss'
        ZEROED = 'ZEROED', 'Near-zero readings'
        BAD_HEALTH = 'BAD_HEALTH', 'Monitor health below threshold'
        MANUAL_REVIEW = 'MANUAL_REVIEW', 'Needs manual review'
        LOW_COVERAGE = 'LOW_COVERAGE', 'Low regional coverage'
        HIGH_VARIANCE = 'HIGH_VARIANCE', 'Monitor disagreement'
        FEW_STATIONS = 'FEW_STATIONS', 'Too few monitors'

    resolution = models.CharField(
        max_length=15,
        choices=Resolution.choices,
        help_text=_('Time interval over which this summary was aggregated (e.g. hourly, daily).')
    )

    timestamp = models.DateTimeField(
        help_text=_('Start time of the aggregation window (e.g. 00:00 for daily summaries).')
    )

    entry_type = EntryTypeField(
        help_text=_('Pollutant or metric being summarized (e.g. PM2.5, Ozone).')
    )

    processor = models.CharField(
        max_length=100,
        blank=True,
        default='',
        db_index=True,
        help_text=_('The processor class used to generate this summary. '
                    'Blank indicates cleaned (uncalibrated) data.')
    )

    count = models.PositiveIntegerField(
        help_text=_('Number of valid entries included in the summary.')
    )
    expected_count = models.PositiveIntegerField(
        help_text=_('Number of entries expected during the resolution window.')
    )

    sum_value = models.FloatField(
        help_text=_('Sum of all valid entry values.')
    )
    sum_of_squares = models.FloatField(
        help_text=_('Sum of squares of all valid entry values (used to calculate variance).')
    )

    minimum = models.FloatField(
        help_text=_('Minimum value observed during the window.')
    )
    maximum = models.FloatField(
        help_text=_('Maximum value observed during the window.')
    )

    mean = models.FloatField(
        help_text=_('Arithmetic mean of all values in the window.')
    )
    stddev = models.FloatField(
        help_text=_('Standard deviation of values during the window.')
    )

    p25 = models.FloatField(
        help_text=_('25th percentile of values (lower quartile).')
    )
    p75 = models.FloatField(
        help_text=_('75th percentile of values (upper quartile).')
    )
    tdigest = JSONField(
        help_text=_('Serialized T-digest object used to compute percentiles efficiently.')
    )

    is_complete = models.BooleanField(
        default=False,
        help_text=_('True if the count is ≥ 80% of expected_count, indicating sufficient coverage.')
    )

    qc_flag = models.CharField(
        max_length=20,
        choices=QCFlag.choices,
        blank=True,
        default=QCFlag.NONE,
        help_text=_('Optional quality control flag indicating potential issues with data.')
    )

    notes = models.TextField(
        blank=True,
        help_text=_('Freeform notes about this summary (e.g. maintenance, known issues).')
    )

    class Meta:
        abstract = True
        indexes = [
            models.Index(fields=['timestamp', 'resolution', 'entry_type']),
        ]


class MonitorSummary(BaseSummary):
    """
    Summary stats for a single monitor and time bucket.
    """

    sqid = SqidsField(alphabet=shuffle_alphabet('summaries.MonitorSummary'))

    monitor = models.ForeignKey(
        Monitor,
        on_delete=models.CASCADE,
        help_text=_('The individual monitor this summary represents.')
    )

    missing_count = models.PositiveIntegerField(
        help_text=_('Number of expected but missing data points in the window.')
    )
    coverage_ratio = models.FloatField(
        help_text=_('Fraction of expected_count that was observed (count / expected_count).')
    )
    downtime_minutes = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text=_('Estimated number of minutes the monitor was offline or unresponsive.')
    )

    class Meta(BaseSummary.Meta):
        unique_together = (
            'monitor', 'entry_type', 'processor', 'resolution', 'timestamp'
        )


class RegionSummary(BaseSummary):
    """
    Combined summary for a region using FEM and calibrated LCS data.
    """

    sqid = SqidsField(alphabet=shuffle_alphabet('summaries.RegionSummary'))

    region = models.ForeignKey(
        Region,
        on_delete=models.CASCADE,
        help_text=_('Geographic region over which the summary is aggregated.')
    )

    station_count = models.PositiveIntegerField(
        help_text=_('Number of monitors that contributed to the region summary.')
    )
    absolute_max = models.FloatField(
        help_text=_('Highest single value reported by any monitor in the region during the window.')
    )
    mean_of_means = models.FloatField(
        help_text=_('Mean of per-monitor means. Captures overall average across sensors.')
    )
    max_of_means = models.FloatField(
        help_text=_('Highest mean reported by any single monitor over the window.')
    )

    interquartile_range = models.FloatField(
        help_text=_('Difference between p75 and p25. Measures variability across sensors.')
    )
    exceedance_count = models.PositiveIntegerField(
        help_text=_('Number of monitors exceeding a relevant health threshold.')
    )
    exceedance_fraction = models.FloatField(
        help_text=_('Fraction of contributing monitors exceeding the health threshold.')
    )

    coverage_ratio = models.FloatField(
        help_text=_('Average data coverage across all contributing monitors in the region.')
    )

    class Meta(BaseSummary.Meta):
        unique_together = (
            'region', 'entry_type', 'processor', 'resolution', 'timestamp'
        )
