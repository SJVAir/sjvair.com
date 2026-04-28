import calendar
from datetime import datetime, timedelta

from django.conf import settings
from django.db.models import Max, Q
from django.utils import timezone

from camp.utils.datetime import localtime, make_aware

from django_huey import db_task, db_periodic_task
from huey import crontab

from camp.apps.entries.fields import EntryTypeField
from camp.apps.entries.stages import Stage
from camp.apps.entries.utils import get_all_entry_models
from camp.apps.monitors.models import Monitor
from camp.apps.regions.models import Region
from camp.apps.summaries.aggregators import compute_monitor_summary, compute_region_summary, rollup_summaries
from camp.apps.summaries.models import BaseSummary, MonitorSummary, RegionSummary


def get_summarizable_entry_models():
    """Return entry models that have opted in to summarization via summarize = True."""
    return [m for m in get_all_entry_models() if m.summarize]


# ---- Hourly tasks ----

@db_periodic_task(crontab(hour='*', minute='5'), priority=50, queue='summaries')
def hourly_monitor_summaries(hour=None):
    """
    Compute hourly MonitorSummary for every (monitor, entry_type, processor) combo
    that has entries in the previous hour. Only RAW (processor='') and CALIBRATED
    (processor≠'') entries are summarized — CORRECTED and CLEANED are skipped.
    """
    if hour is None:
        now = timezone.now().replace(minute=0, second=0, microsecond=0)
        hour = now - timedelta(hours=1)

    for EntryModel in get_summarizable_entry_models():
        combos = (
            EntryModel.objects
            .filter(
                timestamp__gte=hour,
                timestamp__lt=hour + timedelta(hours=1),
            )
            .filter(
                Q(stage=Stage.RAW, processor='') |
                Q(stage=Stage.CALIBRATED)
            )
            .values_list('monitor_id', 'processor')
            .distinct()
        )
        for monitor_id, processor in combos:
            summarize_monitor_hour(str(monitor_id), hour, EntryModel.entry_type, processor)


@db_task(priority=50, queue='summaries')
def summarize_monitor_hour(monitor_id, hour, entry_type, processor):
    """Compute and save one hourly MonitorSummary record."""
    monitor = Monitor.objects.get(pk=monitor_id)
    EntryModel = EntryTypeField.get_model_map()[entry_type]

    stats = compute_monitor_summary(monitor, hour, EntryModel, processor)
    if stats is None:
        return

    MonitorSummary.objects.update_or_create(
        monitor=monitor,
        timestamp=hour,
        resolution=BaseSummary.Resolution.HOURLY,
        entry_type=entry_type,
        processor=processor,
        defaults=stats,
    )


@db_periodic_task(crontab(hour='*', minute='15'), priority=50, queue='summaries')
def hourly_region_summaries(hour=None):
    """
    Compute one hourly RegionSummary per region per entry_type found in
    MonitorSummary records for that hour. Uses each monitor's best available
    calibration — no processor fan-out needed at the region level.
    """
    if hour is None:
        now = timezone.now().replace(minute=0, second=0, microsecond=0)
        hour = now - timedelta(hours=1)

    entry_types = (
        MonitorSummary.objects
        .filter(timestamp=hour, resolution=BaseSummary.Resolution.HOURLY)
        .values_list('entry_type', flat=True)
        .distinct()
    )

    for region in Region.objects.all():
        for entry_type in entry_types:
            summarize_region_hour(str(region.pk), hour, entry_type)


@db_task(priority=50, queue='summaries')
def summarize_region_hour(region_id, hour, entry_type):
    """Compute and save one hourly RegionSummary record."""
    region = Region.objects.get(pk=region_id)

    stats = compute_region_summary(region, hour, entry_type)
    if stats is None:
        return

    RegionSummary.objects.update_or_create(
        region=region,
        timestamp=hour,
        resolution=BaseSummary.Resolution.HOURLY,
        entry_type=entry_type,
        defaults=stats,
    )


# ---- Rollup helpers ----

def rollup_monitor_summaries(target_resolution, source_resolution, window_start, window_end, monitor_ids=None):
    """
    Roll up MonitorSummary records from source_resolution into target_resolution
    for the given time window.

    Finds all distinct (monitor, entry_type, stage, processor) combos in the source
    window and creates/updates one target_resolution record per combo.

    Optionally scoped to a list of monitor_ids (for targeted backfill/recalculation).
    """
    qs = MonitorSummary.objects.filter(
        resolution=source_resolution,
        timestamp__gte=window_start,
        timestamp__lt=window_end,
    )
    if monitor_ids is not None:
        qs = qs.filter(monitor_id__in=monitor_ids)

    combos = qs.values_list('monitor_id', 'entry_type', 'processor').distinct()

    for monitor_id, entry_type, processor in combos:
        source_qs = MonitorSummary.objects.filter(
            monitor_id=monitor_id,
            entry_type=entry_type,
            processor=processor,
            resolution=source_resolution,
            timestamp__gte=window_start,
            timestamp__lt=window_end,
        )
        stats = rollup_summaries(source_qs)
        if stats is None:
            continue

        MonitorSummary.objects.update_or_create(
            monitor_id=monitor_id,
            timestamp=window_start,
            resolution=target_resolution,
            entry_type=entry_type,
            processor=processor,
            defaults=stats,
        )


def rollup_region_summaries(target_resolution, source_resolution, window_start, window_end, region_ids=None):
    """Same as rollup_monitor_summaries but for RegionSummary."""
    qs = RegionSummary.objects.filter(
        resolution=source_resolution,
        timestamp__gte=window_start,
        timestamp__lt=window_end,
    )
    if region_ids is not None:
        qs = qs.filter(region_id__in=region_ids)

    combos = qs.values_list('region_id', 'entry_type').distinct()

    for region_id, entry_type in combos:
        source_qs = RegionSummary.objects.filter(
            region_id=region_id,
            entry_type=entry_type,
            resolution=source_resolution,
            timestamp__gte=window_start,
            timestamp__lt=window_end,
        )
        stats = rollup_summaries(source_qs)
        if stats is None:
            continue

        # station_count: max across the period (most monitors that ever contributed)
        station_count = source_qs.aggregate(
            max_stations=Max('station_count')
        )['max_stations'] or 0

        RegionSummary.objects.update_or_create(
            region_id=region_id,
            timestamp=window_start,
            resolution=target_resolution,
            entry_type=entry_type,
            defaults={**stats, 'station_count': station_count},
        )


# ---- Calendar helpers ----

def _add_3_months(dt):
    """Advance a datetime by exactly 3 calendar months, re-localizing for DST."""
    month = dt.month + 3
    year = dt.year
    if month > 12:
        month -= 12
        year += 1
    return make_aware(datetime(year, month, dt.day), settings.DEFAULT_TIMEZONE)


def _yesterday():
    today = localtime().date()
    yesterday = today - timedelta(days=1)
    return make_aware(datetime(yesterday.year, yesterday.month, yesterday.day), settings.DEFAULT_TIMEZONE)


def _last_month_start():
    today = localtime().date()
    first_of_month = today.replace(day=1)
    last_month_end = first_of_month - timedelta(days=1)
    return make_aware(datetime(last_month_end.year, last_month_end.month, 1), settings.DEFAULT_TIMEZONE)


def _last_quarter_start():
    today = localtime().date()
    quarter_month = ((today.month - 1) // 3) * 3 + 1
    prev_quarter_month = quarter_month - 3
    if prev_quarter_month <= 0:
        return make_aware(datetime(today.year - 1, prev_quarter_month + 12, 1), settings.DEFAULT_TIMEZONE)
    return make_aware(datetime(today.year, prev_quarter_month, 1), settings.DEFAULT_TIMEZONE)


def _last_season_start():
    today = localtime().date()
    end_month = today.month
    start_month = end_month - 3 if end_month > 3 else end_month + 9
    start_year = today.year if end_month > 3 else today.year - 1
    return make_aware(datetime(start_year, start_month, 1), settings.DEFAULT_TIMEZONE)


# ---- Rollup periodic tasks ----

@db_periodic_task(crontab(hour='0', minute='15'), priority=50, queue='summaries')
def daily_monitor_summaries(day=None):
    """Roll up yesterday's hourly MonitorSummary records into daily ones."""
    day = day or _yesterday()
    rollup_monitor_summaries(BaseSummary.Resolution.DAILY, BaseSummary.Resolution.HOURLY, day, day + timedelta(days=1))


@db_periodic_task(crontab(hour='0', minute='25'), priority=50, queue='summaries')
def daily_region_summaries(day=None):
    """Roll up yesterday's hourly RegionSummary records into daily ones."""
    day = day or _yesterday()
    rollup_region_summaries(BaseSummary.Resolution.DAILY, BaseSummary.Resolution.HOURLY, day, day + timedelta(days=1))


@db_periodic_task(crontab(day='1', hour='0', minute='30'), priority=50, queue='summaries')
def monthly_monitor_summaries(month_start=None):
    """Roll up last month's daily MonitorSummary records into monthly ones."""
    month_start = month_start or _last_month_start()
    _, days_in_month = calendar.monthrange(month_start.year, month_start.month)
    rollup_monitor_summaries(BaseSummary.Resolution.MONTHLY, BaseSummary.Resolution.DAILY, month_start, month_start + timedelta(days=days_in_month))


@db_periodic_task(crontab(day='1', hour='0', minute='40'), priority=50, queue='summaries')
def monthly_region_summaries(month_start=None):
    """Roll up last month's daily RegionSummary records into monthly ones."""
    month_start = month_start or _last_month_start()
    _, days_in_month = calendar.monthrange(month_start.year, month_start.month)
    rollup_region_summaries(BaseSummary.Resolution.MONTHLY, BaseSummary.Resolution.DAILY, month_start, month_start + timedelta(days=days_in_month))


@db_periodic_task(crontab(month='1,4,7,10', day='1', hour='0', minute='45'), priority=50, queue='summaries')
def quarterly_monitor_summaries(quarter_start=None):
    """Roll up last quarter's monthly MonitorSummary records into quarterly ones."""
    quarter_start = quarter_start or _last_quarter_start()
    rollup_monitor_summaries(BaseSummary.Resolution.QUARTERLY, BaseSummary.Resolution.MONTHLY, quarter_start, _add_3_months(quarter_start))


@db_periodic_task(crontab(month='1,4,7,10', day='1', hour='0', minute='50'), priority=50, queue='summaries')
def quarterly_region_summaries(quarter_start=None):
    """Roll up last quarter's monthly RegionSummary records into quarterly ones."""
    quarter_start = quarter_start or _last_quarter_start()
    rollup_region_summaries(BaseSummary.Resolution.QUARTERLY, BaseSummary.Resolution.MONTHLY, quarter_start, _add_3_months(quarter_start))


@db_periodic_task(crontab(month='3,6,9,12', day='1', hour='1', minute='0'), priority=50, queue='summaries')
def seasonal_monitor_summaries(season_start=None):
    """
    Roll up the past 3 months of monthly MonitorSummary records into a seasonal one.
    Runs Mar 1, Jun 1, Sep 1, Dec 1 to summarize the just-completed season.
    """
    season_start = season_start or _last_season_start()
    rollup_monitor_summaries(BaseSummary.Resolution.SEASONAL, BaseSummary.Resolution.MONTHLY, season_start, _add_3_months(season_start))


@db_periodic_task(crontab(month='3,6,9,12', day='1', hour='1', minute='10'), priority=50, queue='summaries')
def seasonal_region_summaries(season_start=None):
    """Roll up the past 3 months of monthly RegionSummary records into a seasonal one."""
    season_start = season_start or _last_season_start()
    rollup_region_summaries(BaseSummary.Resolution.SEASONAL, BaseSummary.Resolution.MONTHLY, season_start, _add_3_months(season_start))


@db_periodic_task(crontab(month='1', day='1', hour='1', minute='15'), priority=50, queue='summaries')
def yearly_monitor_summaries(year_start=None):
    """Roll up last year's monthly MonitorSummary records into yearly ones."""
    if year_start is None:
        today = localtime().date()
        year_start = make_aware(datetime(today.year - 1, 1, 1), settings.DEFAULT_TIMEZONE)
    rollup_monitor_summaries(BaseSummary.Resolution.YEARLY, BaseSummary.Resolution.MONTHLY, year_start, year_start.replace(year=year_start.year + 1))


@db_periodic_task(crontab(month='1', day='1', hour='1', minute='20'), priority=50, queue='summaries')
def yearly_region_summaries(year_start=None):
    """Roll up last year's monthly RegionSummary records into yearly ones."""
    if year_start is None:
        today = localtime().date()
        year_start = make_aware(datetime(today.year - 1, 1, 1), settings.DEFAULT_TIMEZONE)
    rollup_region_summaries(BaseSummary.Resolution.YEARLY, BaseSummary.Resolution.MONTHLY, year_start, year_start.replace(year=year_start.year + 1))
