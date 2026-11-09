from collections import defaultdict
from datetime import datetime, timedelta
from functools import reduce
import operator

from django.conf import settings
from django.db.models import Count, Exists, OuterRef, Q
from django.db.models.functions import TruncHour

from camp.utils.datetime import localtime, make_aware
from camp.apps.summaries.periods import is_period_start, iter_hours, iter_period_starts, period_end
from camp.apps.summaries.models import BaseSummary
from camp.apps.entries.stages import Stage
from camp.apps.monitors.models import Monitor
from camp.apps.regions.models import Region
from camp.apps.summaries.aggregators import compute_stats, compute_region_summary, hourly_output_processor
from camp.apps.summaries.models import MonitorSummary, RegionSummary
from camp.apps.summaries.selection import region_summary_entry_models


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


def monitors_with_data_in(chunk_start, chunk_end, entry_models, scoped_entry_models=None):
    """
    Monitor ids with at least one entry of any given type in [chunk_start, chunk_end).

    `scoped_entry_models` ({EntryModel: [monitor types]}) adds types checked
    only on monitors of the listed types (one query per monitor type), so
    other monitor types never pay their Exists.
    """
    def has_data(EntryModel):
        return Exists(EntryModel.objects.filter(
            monitor_id=OuterRef('pk'),
            timestamp__gte=chunk_start,
            timestamp__lt=chunk_end,
        ))

    combined = reduce(operator.or_, [has_data(EntryModel) for EntryModel in entry_models])
    monitor_ids = list(Monitor.objects.filter(combined).values_list('pk', flat=True).distinct())

    by_type = defaultdict(list)
    for EntryModel, monitor_types in (scoped_entry_models or {}).items():
        for monitor_type in monitor_types:
            by_type[monitor_type].append(EntryModel)
    seen = set(monitor_ids)
    for monitor_type, models in by_type.items():
        combined = reduce(operator.or_, [has_data(EntryModel) for EntryModel in models])
        for pk in monitor_type.objects.filter(combined).values_list('pk', flat=True).distinct():
            if pk not in seen:
                seen.add(pk)
                monitor_ids.append(pk)
    return monitor_ids


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

        # Hourly-output series: one grouped query counts each hour's source readings.
        source_counts = {}
        classes = {p: hourly_output_processor(p) for p in {p for _, p in groups}}
        classes = {p: c for p, c in classes.items() if c is not None}
        for stage in {c.source_stage for c in classes.values()}:
            source_counts[stage] = dict(
                EntryModel.objects
                .filter(
                    monitor_id=monitor.pk,
                    timestamp__gte=chunk_start,
                    timestamp__lt=chunk_end,
                    stage=stage,
                )
                .annotate(hour=TruncHour('timestamp'))
                .values_list('hour')
                .annotate(n=Count('pk'))
                .order_by()
            )

        expected = monitor.expected_hourly_entries or 1
        for (hour, processor), values in groups.items():
            cls = classes.get(processor)
            if cls is None:
                stats = compute_stats(values, expected)
            else:
                n = source_counts[cls.source_stage].get(hour, 0)
                stats = compute_stats(values, 1, is_complete=n >= 0.8 * expected)
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
    # Only the region types: weather types (CIMIS) have monitor rows, never region rows.
    region_types = [m.entry_type for m in region_summary_entry_models()]
    to_upsert = []
    for hour in hours:
        entry_types = list(
            MonitorSummary.objects
            .filter(timestamp=hour, resolution=BaseSummary.Resolution.HOURLY, entry_type__in=region_types)
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
