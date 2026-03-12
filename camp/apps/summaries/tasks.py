import calendar
from datetime import timedelta

from django.db.models import Max
from django.utils import timezone

from django_huey import db_task, db_periodic_task
from huey import crontab

from camp.apps.monitors.models import Monitor


def get_summarizable_entry_models():
    """Return entry models that have opted in to summarization via summarize = True."""
    from camp.apps.entries.utils import get_all_entry_models
    return [m for m in get_all_entry_models() if m.summarize]


# ---- Hourly tasks ----

@db_periodic_task(crontab(hour='*', minute='5'), priority=50)
def hourly_monitor_summaries(hour=None):
    """
    Compute hourly MonitorSummary for every (monitor, entry_type, stage, processor)
    combo that has entries in the previous hour.
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
            .values_list('monitor_id', 'stage', 'processor')
            .distinct()
        )
        for monitor_id, stage, processor in combos:
            summarize_monitor_hour(str(monitor_id), hour, EntryModel.entry_type, stage, processor)


@db_task(priority=50)
def summarize_monitor_hour(monitor_id, hour, entry_type, stage, processor):
    """Compute and save one hourly MonitorSummary record."""
    from camp.apps.entries.fields import EntryTypeField
    from camp.apps.summaries.aggregators import compute_monitor_summary
    from camp.apps.summaries.models import MonitorSummary, BaseSummary

    monitor = Monitor.objects.get(pk=monitor_id)
    EntryModel = EntryTypeField.get_model_map()[entry_type]

    stats = compute_monitor_summary(monitor, hour, EntryModel, stage, processor)
    if stats is None:
        return

    MonitorSummary.objects.update_or_create(
        monitor=monitor,
        timestamp=hour,
        resolution=BaseSummary.Resolution.HOURLY,
        entry_type=entry_type,
        stage=stage,
        processor=processor,
        defaults=stats,
    )


@db_periodic_task(crontab(hour='*', minute='15'), priority=50)
def hourly_region_summaries(hour=None):
    """
    Compute hourly RegionSummary for each region, for each (entry_type, stage, processor)
    combo found in MonitorSummary records for that hour.
    """
    from camp.apps.regions.models import Region
    from camp.apps.summaries.models import MonitorSummary, BaseSummary

    if hour is None:
        now = timezone.now().replace(minute=0, second=0, microsecond=0)
        hour = now - timedelta(hours=1)

    combos = (
        MonitorSummary.objects
        .filter(timestamp=hour, resolution=BaseSummary.Resolution.HOURLY)
        .values_list('entry_type', 'stage', 'processor')
        .distinct()
    )

    for region in Region.objects.all():
        for entry_type, stage, processor in combos:
            summarize_region_hour(str(region.pk), hour, entry_type, stage, processor)


@db_task(priority=50)
def summarize_region_hour(region_id, hour, entry_type, stage, processor):
    """Compute and save one hourly RegionSummary record."""
    from camp.apps.regions.models import Region
    from camp.apps.summaries.aggregators import compute_region_summary
    from camp.apps.summaries.models import RegionSummary, BaseSummary

    region = Region.objects.get(pk=region_id)

    stats = compute_region_summary(region, hour, entry_type, stage, processor)
    if stats is None:
        return

    RegionSummary.objects.update_or_create(
        region=region,
        timestamp=hour,
        resolution=BaseSummary.Resolution.HOURLY,
        entry_type=entry_type,
        stage=stage,
        processor=processor,
        defaults=stats,
    )


# ---- Rollup helpers ----

def rollup_monitor_summaries(target_resolution, source_resolution, window_start, window_end):
    """
    Roll up MonitorSummary records from source_resolution into target_resolution
    for the given time window.

    Finds all distinct (monitor, entry_type, stage, processor) combos in the source
    window and creates/updates one target_resolution record per combo.
    """
    from camp.apps.summaries.aggregators import rollup_summaries
    from camp.apps.summaries.models import MonitorSummary

    combos = (
        MonitorSummary.objects
        .filter(
            resolution=source_resolution,
            timestamp__gte=window_start,
            timestamp__lt=window_end,
        )
        .values_list('monitor_id', 'entry_type', 'stage', 'processor')
        .distinct()
    )

    for monitor_id, entry_type, stage, processor in combos:
        source_qs = MonitorSummary.objects.filter(
            monitor_id=monitor_id,
            entry_type=entry_type,
            stage=stage,
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
            stage=stage,
            processor=processor,
            defaults=stats,
        )


def rollup_region_summaries(target_resolution, source_resolution, window_start, window_end):
    """Same as rollup_monitor_summaries but for RegionSummary."""
    from camp.apps.summaries.aggregators import rollup_summaries
    from camp.apps.summaries.models import RegionSummary

    combos = (
        RegionSummary.objects
        .filter(
            resolution=source_resolution,
            timestamp__gte=window_start,
            timestamp__lt=window_end,
        )
        .values_list('region_id', 'entry_type', 'stage', 'processor')
        .distinct()
    )

    for region_id, entry_type, stage, processor in combos:
        source_qs = RegionSummary.objects.filter(
            region_id=region_id,
            entry_type=entry_type,
            stage=stage,
            processor=processor,
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
            stage=stage,
            processor=processor,
            defaults={**stats, 'station_count': station_count},
        )


# ---- Calendar helpers ----

def _yesterday():
    today = timezone.now().replace(hour=0, minute=0, second=0, microsecond=0)
    return today - timedelta(days=1)


def _last_month_start():
    today = timezone.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_month = today - timedelta(days=1)
    return last_month.replace(day=1)


def _last_quarter_start():
    today = timezone.now()
    quarter_month = ((today.month - 1) // 3) * 3 + 1
    current_quarter_start = today.replace(month=quarter_month, day=1, hour=0, minute=0, second=0, microsecond=0)
    if quarter_month == 1:
        return current_quarter_start.replace(year=current_quarter_start.year - 1, month=10)
    return current_quarter_start.replace(month=quarter_month - 3)


def _last_season_start():
    today = timezone.now()
    end_month = today.month
    start_month = end_month - 3 if end_month > 3 else end_month + 9
    start_year = today.year if end_month > 3 else today.year - 1
    return today.replace(year=start_year, month=start_month, day=1, hour=0, minute=0, second=0, microsecond=0)


# ---- Rollup periodic tasks ----

@db_periodic_task(crontab(hour='0', minute='15'), priority=50)
def daily_monitor_summaries(day=None):
    """Roll up yesterday's hourly MonitorSummary records into daily ones."""
    from camp.apps.summaries.models import BaseSummary
    day = day or _yesterday()
    rollup_monitor_summaries(BaseSummary.Resolution.DAILY, BaseSummary.Resolution.HOURLY, day, day + timedelta(days=1))


@db_periodic_task(crontab(hour='0', minute='25'), priority=50)
def daily_region_summaries(day=None):
    """Roll up yesterday's hourly RegionSummary records into daily ones."""
    from camp.apps.summaries.models import BaseSummary
    day = day or _yesterday()
    rollup_region_summaries(BaseSummary.Resolution.DAILY, BaseSummary.Resolution.HOURLY, day, day + timedelta(days=1))


@db_periodic_task(crontab(day='1', hour='0', minute='30'), priority=50)
def monthly_monitor_summaries(month_start=None):
    """Roll up last month's daily MonitorSummary records into monthly ones."""
    from camp.apps.summaries.models import BaseSummary
    month_start = month_start or _last_month_start()
    _, days_in_month = calendar.monthrange(month_start.year, month_start.month)
    rollup_monitor_summaries(BaseSummary.Resolution.MONTHLY, BaseSummary.Resolution.DAILY, month_start, month_start + timedelta(days=days_in_month))


@db_periodic_task(crontab(day='1', hour='0', minute='40'), priority=50)
def monthly_region_summaries(month_start=None):
    """Roll up last month's daily RegionSummary records into monthly ones."""
    from camp.apps.summaries.models import BaseSummary
    month_start = month_start or _last_month_start()
    _, days_in_month = calendar.monthrange(month_start.year, month_start.month)
    rollup_region_summaries(BaseSummary.Resolution.MONTHLY, BaseSummary.Resolution.DAILY, month_start, month_start + timedelta(days=days_in_month))


@db_periodic_task(crontab(month='1,4,7,10', day='1', hour='0', minute='45'), priority=50)
def quarterly_monitor_summaries(quarter_start=None):
    """Roll up last quarter's monthly MonitorSummary records into quarterly ones."""
    from camp.apps.summaries.models import BaseSummary
    quarter_start = quarter_start or _last_quarter_start()
    rollup_monitor_summaries(BaseSummary.Resolution.QUARTERLY, BaseSummary.Resolution.MONTHLY, quarter_start, quarter_start + timedelta(days=92))


@db_periodic_task(crontab(month='1,4,7,10', day='1', hour='0', minute='50'), priority=50)
def quarterly_region_summaries(quarter_start=None):
    """Roll up last quarter's monthly RegionSummary records into quarterly ones."""
    from camp.apps.summaries.models import BaseSummary
    quarter_start = quarter_start or _last_quarter_start()
    rollup_region_summaries(BaseSummary.Resolution.QUARTERLY, BaseSummary.Resolution.MONTHLY, quarter_start, quarter_start + timedelta(days=92))


@db_periodic_task(crontab(month='3,6,9,12', day='1', hour='1', minute='0'), priority=50)
def seasonal_monitor_summaries(season_start=None):
    """
    Roll up the past 3 months of monthly MonitorSummary records into a seasonal one.
    Runs Mar 1, Jun 1, Sep 1, Dec 1 to summarize the just-completed season.
    """
    from camp.apps.summaries.models import BaseSummary
    season_start = season_start or _last_season_start()
    rollup_monitor_summaries(BaseSummary.Resolution.SEASONAL, BaseSummary.Resolution.MONTHLY, season_start, season_start + timedelta(days=92))


@db_periodic_task(crontab(month='3,6,9,12', day='1', hour='1', minute='10'), priority=50)
def seasonal_region_summaries(season_start=None):
    """Roll up the past 3 months of monthly RegionSummary records into a seasonal one."""
    from camp.apps.summaries.models import BaseSummary
    season_start = season_start or _last_season_start()
    rollup_region_summaries(BaseSummary.Resolution.SEASONAL, BaseSummary.Resolution.MONTHLY, season_start, season_start + timedelta(days=92))


@db_periodic_task(crontab(month='1', day='1', hour='1', minute='15'), priority=50)
def yearly_monitor_summaries(year_start=None):
    """Roll up last year's monthly MonitorSummary records into yearly ones."""
    from camp.apps.summaries.models import BaseSummary
    if year_start is None:
        today = timezone.now()
        year_start = today.replace(year=today.year - 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    rollup_monitor_summaries(BaseSummary.Resolution.YEARLY, BaseSummary.Resolution.MONTHLY, year_start, year_start.replace(year=year_start.year + 1))


@db_periodic_task(crontab(month='1', day='1', hour='1', minute='20'), priority=50)
def yearly_region_summaries(year_start=None):
    """Roll up last year's monthly RegionSummary records into yearly ones."""
    from camp.apps.summaries.models import BaseSummary
    if year_start is None:
        today = timezone.now()
        year_start = today.replace(year=today.year - 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    rollup_region_summaries(BaseSummary.Resolution.YEARLY, BaseSummary.Resolution.MONTHLY, year_start, year_start.replace(year=year_start.year + 1))
