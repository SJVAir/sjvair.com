from collections import defaultdict
from datetime import datetime, timedelta
from functools import reduce
import operator

from django.conf import settings
from django.db.models import Exists, OuterRef, Q

from camp.utils.datetime import localtime, make_aware
from camp.apps.summaries.periods import is_period_start, iter_hours, iter_period_starts, period_end
from camp.apps.summaries.models import BaseSummary
from camp.apps.entries.stages import Stage
from camp.apps.monitors.models import Monitor
from camp.apps.regions.models import Region
from camp.apps.summaries.aggregators import compute_stats, compute_region_summary
from camp.apps.summaries.models import MonitorSummary, RegionSummary


DEFAULT_CHUNK_DAYS = 1


def chunk_start_for(cursor, range_start, chunk_days=DEFAULT_CHUNK_DAYS):
    """
    The lower bound of the next chunk to process, walking backward from cursor.
    Steps whole Pacific calendar days, so the result is always a Pacific
    midnight even when `cursor` comes back from the database as UTC.
    """
    target = localtime(cursor).date() - timedelta(days=chunk_days)
    return max(make_aware(datetime(target.year, target.month, target.day), settings.DEFAULT_TIMEZONE), range_start)


hour_range = iter_hours


def iter_chunk_days(chunk_start, chunk_end):
    """Yield each Pacific day start in [chunk_start, chunk_end). `chunk_start` is a Pacific midnight."""
    return iter_period_starts('day', chunk_start, chunk_end)


def daily_rollup_window(day):
    """The (target, source, window_start, window_end) tuple to roll up a single day."""
    return (BaseSummary.Resolution.DAILY, BaseSummary.Resolution.HOURLY, day, period_end('day', day))


def higher_rollup_windows(day):
    """
    Return the (target, source, window_start, window_end) rollup windows that
    become fully covered once `day` — the earliest day of a chunk, walking
    backward — has been processed. Empty unless `day` is the first of a
    month: only then can a month (and possibly quarter/season/year) be
    confirmed complete, since every later day in that period was necessarily
    already processed on an earlier (more recent) tick.
    """
    local = localtime(day)
    if not is_period_start('day', day) or local.day != 1:
        return []

    R = BaseSummary.Resolution
    windows = [(R.MONTHLY, R.DAILY, day, period_end('month', day))]

    if local.month in (1, 4, 7, 10):
        windows.append((R.QUARTERLY, R.MONTHLY, day, period_end('quarter', day)))

    if local.month in (12, 3, 6, 9):
        windows.append((R.SEASONAL, R.MONTHLY, day, period_end('season', day)))

    if local.month == 1:
        windows.append((R.YEARLY, R.MONTHLY, day, period_end('year', day)))

    return windows


def monitors_with_data_in(chunk_start, chunk_end, entry_models):
    """Monitor ids with at least one entry of any given type in [chunk_start, chunk_end)."""
    conditions = [
        Exists(EntryModel.objects.filter(
            monitor_id=OuterRef('pk'),
            timestamp__gte=chunk_start,
            timestamp__lt=chunk_end,
        ))
        for EntryModel in entry_models
    ]
    combined = reduce(operator.or_, conditions)
    return list(Monitor.objects.filter(combined).values_list('pk', flat=True).distinct())


def regions_with_monitors():
    """Region ids that have at least one monitor located inside their boundary."""
    return list(
        Region.objects
        .filter(
            Exists(Monitor.objects.filter(
                position__isnull=False,
                position__intersects=OuterRef('boundary__geometry'),
            )),
            boundary__isnull=False,
        )
        .values_list('pk', flat=True)
    )


def backfill_monitor_hours(monitor, chunk_start, chunk_end, entry_models):
    """
    Compute and upsert hourly MonitorSummary rows for one monitor across
    [chunk_start, chunk_end). One query per entry model, regardless of how
    many hours the chunk spans. Returns the number of summaries written.
    """
    to_upsert = []
    for EntryModel in entry_models:
        rows = (
            EntryModel.objects
            .filter(
                monitor_id=monitor.pk,
                timestamp__gte=chunk_start,
                timestamp__lt=chunk_end,
            )
            .filter(Q(stage=Stage.RAW, processor='') | Q(stage=Stage.CALIBRATED))
            .values_list('timestamp', 'processor', 'value')
        )

        groups = defaultdict(list)
        for ts, processor, value in rows:
            if value is not None:
                hour = ts.replace(minute=0, second=0, microsecond=0)
                groups[(hour, processor)].append(float(value))

        for (hour, processor), values in groups.items():
            stats = compute_stats(values, monitor.expected_hourly_entries or 1)
            if stats is None:
                continue
            to_upsert.append(MonitorSummary(
                monitor_id=monitor.pk,
                timestamp=hour,
                resolution=BaseSummary.Resolution.HOURLY,
                entry_type=EntryModel.entry_type,
                processor=processor,
                **stats,
            ))

    if to_upsert:
        MonitorSummary.objects.bulk_create(
            to_upsert,
            update_conflicts=True,
            unique_fields=['monitor', 'entry_type', 'processor', 'resolution', 'timestamp'],
            update_fields=[
                'count', 'expected_count', 'sum_value', 'sum_of_squares',
                'minimum', 'maximum', 'mean', 'stddev', 'p25', 'p75',
                'tdigest', 'is_complete',
            ],
        )
    return len(to_upsert)


def backfill_region_hours(region, hours, monitor_grades):
    """
    Compute and upsert hourly RegionSummary rows for one region across the
    given hours, using precomputed monitor_grades ({monitor_id: grade}) to
    avoid a geospatial query per hour. Returns the number of summaries written.
    """
    to_upsert = []
    for hour in hours:
        entry_types = list(
            MonitorSummary.objects
            .filter(timestamp=hour, resolution=BaseSummary.Resolution.HOURLY)
            .values_list('entry_type', flat=True)
            .distinct()
        )
        for entry_type in entry_types:
            stats = compute_region_summary(region, hour, entry_type, monitor_grades=monitor_grades)
            if stats is None:
                continue
            to_upsert.append(RegionSummary(
                region=region,
                timestamp=hour,
                resolution=BaseSummary.Resolution.HOURLY,
                entry_type=entry_type,
                **stats,
            ))

    if to_upsert:
        RegionSummary.objects.bulk_create(
            to_upsert,
            update_conflicts=True,
            unique_fields=['region', 'entry_type', 'resolution', 'timestamp'],
            update_fields=[
                'count', 'weight', 'expected_count', 'sum_value', 'sum_of_squares',
                'minimum', 'maximum', 'mean', 'stddev', 'p25', 'p75',
                'tdigest', 'station_count',
            ],
        )
    return len(to_upsert)
