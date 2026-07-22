import calendar
import logging
import os
from collections import defaultdict
from datetime import datetime, timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Exists, F, OuterRef, Q
from django.utils import timezone

from camp.utils.datetime import localtime, make_aware

from django_huey import db_task, db_periodic_task
from huey import crontab

from camp.apps.entries.fields import EntryTypeField
from camp.apps.entries.stages import Stage
from camp.apps.entries.utils import get_all_entry_models
from camp.apps.monitors.models import Monitor
from camp.apps.regions.models import Region
from camp.apps.summaries.aggregators import compute_monitor_summary, compute_region_summary, rollup_summaries, rollup_region_stats
from camp.apps.summaries.backfill import (
    backfill_monitor_hours,
    backfill_region_hours,
    chunk_start_for,
    daily_rollup_window,
    higher_rollup_windows,
    hour_range,
    iter_chunk_days,
    monitors_with_data_in,
    regions_with_monitors,
)
from camp.apps.summaries.models import BaseSummary, MonitorSummary, RegionSummary, SummaryBackfillJob


def get_summarizable_entry_models():
    """Return entry models that have opted in to summarization via summarize = True."""
    return [m for m in get_all_entry_models() if m.summarize]


# ---- Hourly tasks ----

# Task priorities decrease with dependency depth so upstream data is always
# ready before downstream aggregations consume it:
#   hourly monitor (100) → hourly region (90) → daily monitor (80) → daily region (70)
#   → monthly monitor (60) → monthly region (50) → quarterly monitor (40) → quarterly region (30)
#   → seasonal monitor (20) → seasonal region (15) → yearly monitor (10) → yearly region (5)

@db_periodic_task(crontab(hour='*', minute='5'), priority=100, queue='summaries')
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


@db_task(priority=100, queue='summaries')
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


@db_periodic_task(crontab(hour='*', minute='15'), priority=90, queue='summaries')
def hourly_region_summaries(hour=None):
    """
    Compute one hourly RegionSummary per region per entry_type found in
    MonitorSummary records for that hour. Uses each monitor's best available
    calibration — no processor fan-out needed at the region level.
    """
    if hour is None:
        now = timezone.now().replace(minute=0, second=0, microsecond=0)
        hour = now - timedelta(hours=1)

    entry_models = get_summarizable_entry_models()

    regions = (Region.objects
        .filter(
            Exists(
                Monitor.objects.filter(
                    position__isnull=False,
                    position__intersects=OuterRef('boundary__geometry'),
                )
            ),
            boundary__isnull=False
        )
    )

    for region in regions:
        for EntryModel in entry_models:
            summarize_region_hour(str(region.pk), hour, EntryModel.entry_type)


@db_task(priority=90, queue='summaries')
def summarize_region_hour(region_id, hour, entry_type):
    """Compute and save one hourly RegionSummary record."""
    region = Region.objects.select_related('boundary').get(pk=region_id)

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

    Fetches all source records in one query, groups by (monitor, entry_type, processor)
    in Python, then batch-upserts the results.

    Optionally scoped to a list of monitor_ids (for targeted backfill/recalculation).
    """
    qs = MonitorSummary.objects.filter(
        resolution=source_resolution,
        timestamp__gte=window_start,
        timestamp__lt=window_end,
    )
    if monitor_ids is not None:
        qs = qs.filter(monitor_id__in=monitor_ids)

    records = list(qs.values(
        'monitor_id', 'entry_type', 'processor',
        'count', 'expected_count', 'sum_value', 'sum_of_squares',
        'minimum', 'maximum', 'tdigest',
    ))

    if not records:
        return

    groups = defaultdict(list)
    for r in records:
        groups[(r['monitor_id'], r['entry_type'], r['processor'])].append(r)

    to_upsert = []
    for (monitor_id, entry_type, processor), group_records in groups.items():
        stats = rollup_summaries(group_records)
        if stats is None:
            continue
        to_upsert.append(MonitorSummary(
            monitor_id=monitor_id,
            timestamp=window_start,
            resolution=target_resolution,
            entry_type=entry_type,
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


def rollup_region_summaries(target_resolution, source_resolution, window_start, window_end, region_ids=None):
    """Same as rollup_monitor_summaries but for RegionSummary."""
    qs = RegionSummary.objects.filter(
        resolution=source_resolution,
        timestamp__gte=window_start,
        timestamp__lt=window_end,
    )
    if region_ids is not None:
        qs = qs.filter(region_id__in=region_ids)

    records = list(qs.values(
        'region_id', 'entry_type', 'station_count',
        'count', 'weight', 'expected_count', 'sum_value', 'sum_of_squares',
        'minimum', 'maximum', 'tdigest',
    ))

    if not records:
        return

    groups = defaultdict(list)
    for r in records:
        groups[(r['region_id'], r['entry_type'])].append(r)

    to_upsert = []
    for (region_id, entry_type), group_records in groups.items():
        stats = rollup_region_stats(group_records)
        if stats is None:
            continue
        # station_count: max across the period (most monitors that ever contributed)
        station_count = max(r['station_count'] for r in group_records)
        to_upsert.append(RegionSummary(
            region_id=region_id,
            timestamp=window_start,
            resolution=target_resolution,
            entry_type=entry_type,
            station_count=station_count,
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

@db_periodic_task(crontab(hour='0', minute='15'), priority=80, queue='summaries')
def daily_monitor_summaries(day=None):
    """Roll up yesterday's hourly MonitorSummary records into daily ones."""
    day = day or _yesterday()
    rollup_monitor_summaries(BaseSummary.Resolution.DAILY, BaseSummary.Resolution.HOURLY, day, day + timedelta(days=1))


@db_periodic_task(crontab(hour='0', minute='25'), priority=70, queue='summaries')
def daily_region_summaries(day=None):
    """Roll up yesterday's hourly RegionSummary records into daily ones."""
    day = day or _yesterday()
    rollup_region_summaries(BaseSummary.Resolution.DAILY, BaseSummary.Resolution.HOURLY, day, day + timedelta(days=1))


@db_periodic_task(crontab(day='1', hour='0', minute='30'), priority=60, queue='summaries')
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


@db_periodic_task(crontab(month='1,4,7,10', day='1', hour='0', minute='45'), priority=40, queue='summaries')
def quarterly_monitor_summaries(quarter_start=None):
    """Roll up last quarter's monthly MonitorSummary records into quarterly ones."""
    quarter_start = quarter_start or _last_quarter_start()
    rollup_monitor_summaries(BaseSummary.Resolution.QUARTERLY, BaseSummary.Resolution.MONTHLY, quarter_start, _add_3_months(quarter_start))


@db_periodic_task(crontab(month='1,4,7,10', day='1', hour='0', minute='50'), priority=30, queue='summaries')
def quarterly_region_summaries(quarter_start=None):
    """Roll up last quarter's monthly RegionSummary records into quarterly ones."""
    quarter_start = quarter_start or _last_quarter_start()
    rollup_region_summaries(BaseSummary.Resolution.QUARTERLY, BaseSummary.Resolution.MONTHLY, quarter_start, _add_3_months(quarter_start))


@db_periodic_task(crontab(month='3,6,9,12', day='1', hour='1', minute='0'), priority=20, queue='summaries')
def seasonal_monitor_summaries(season_start=None):
    """
    Roll up the past 3 months of monthly MonitorSummary records into a seasonal one.
    Runs Mar 1, Jun 1, Sep 1, Dec 1 to summarize the just-completed season.
    """
    season_start = season_start or _last_season_start()
    rollup_monitor_summaries(BaseSummary.Resolution.SEASONAL, BaseSummary.Resolution.MONTHLY, season_start, _add_3_months(season_start))


@db_periodic_task(crontab(month='3,6,9,12', day='1', hour='1', minute='10'), priority=15, queue='summaries')
def seasonal_region_summaries(season_start=None):
    """Roll up the past 3 months of monthly RegionSummary records into a seasonal one."""
    season_start = season_start or _last_season_start()
    rollup_region_summaries(BaseSummary.Resolution.SEASONAL, BaseSummary.Resolution.MONTHLY, season_start, _add_3_months(season_start))


@db_periodic_task(crontab(month='1', day='1', hour='1', minute='15'), priority=10, queue='summaries')
def yearly_monitor_summaries(year_start=None):
    """Roll up last year's monthly MonitorSummary records into yearly ones."""
    if year_start is None:
        today = localtime().date()
        year_start = make_aware(datetime(today.year - 1, 1, 1), settings.DEFAULT_TIMEZONE)
    rollup_monitor_summaries(BaseSummary.Resolution.YEARLY, BaseSummary.Resolution.MONTHLY, year_start, year_start.replace(year=year_start.year + 1))


@db_periodic_task(crontab(month='1', day='1', hour='1', minute='20'), priority=5, queue='summaries')
def yearly_region_summaries(year_start=None):
    """Roll up last year's monthly RegionSummary records into yearly ones."""
    if year_start is None:
        today = localtime().date()
        year_start = make_aware(datetime(today.year - 1, 1, 1), settings.DEFAULT_TIMEZONE)
    rollup_region_summaries(BaseSummary.Resolution.YEARLY, BaseSummary.Resolution.MONTHLY, year_start, year_start.replace(year=year_start.year + 1))


# ---- Backfill ----

@db_task(priority=1, queue='summaries')
def backfill_monitor_chunk(job_id, monitor_id, chunk_start, chunk_end, batch_id):
    """Compute one monitor's hourly summaries for a backfill chunk, then report completion."""
    monitor = Monitor.objects.get(pk=monitor_id)
    entry_models = get_summarizable_entry_models()
    backfill_monitor_hours(monitor, chunk_start, chunk_end, entry_models)

    SummaryBackfillJob.objects.filter(
        pk=job_id, batch_id=batch_id, phase=SummaryBackfillJob.Phase.MONITORS,
    ).update(pending_tasks=F('pending_tasks') - 1)


@db_task(priority=1, queue='summaries')
def backfill_region_chunk(job_id, region_id, chunk_start, chunk_end, batch_id):
    """Compute one region's hourly summaries for a backfill chunk, then report completion."""
    region = Region.objects.select_related('boundary').get(pk=region_id)
    monitor_grades = dict(region.monitors.with_grade().values_list('pk', 'grade'))
    hours = list(hour_range(chunk_start, chunk_end))
    backfill_region_hours(region, hours, monitor_grades)

    SummaryBackfillJob.objects.filter(
        pk=job_id, batch_id=batch_id, phase=SummaryBackfillJob.Phase.REGIONS,
    ).update(pending_tasks=F('pending_tasks') - 1)


# ---- Backfill orchestrator ----

BACKFILL_LOCK_STALE_SECONDS = 30
BACKFILL_BATCH_STALE_MINUTES = 60
BACKFILL_MAX_CONSECUTIVE_FAILURES = 5


@db_periodic_task(crontab(minute='*'), priority=1, queue='summaries')
def backfill_summaries_tick():
    """
    Drive one step of the active SummaryBackfillJob, if any. Never blocks on
    the sub-tasks it dispatches — it only checks whether the current phase's
    batch has drained (pending_tasks == 0) and, if so, advances to the next
    phase. See docs/superpowers/specs/2026-07-13-summary-backfill-design.md.
    """
    now = timezone.now()

    with transaction.atomic():
        job = (
            SummaryBackfillJob.objects
            .select_for_update(skip_locked=True)
            .filter(state=SummaryBackfillJob.State.RUNNING)
            .filter(
                Q(locked_at__isnull=True) |
                Q(locked_at__lt=now - timedelta(seconds=BACKFILL_LOCK_STALE_SECONDS))
            )
            .order_by('created')
            .first()
        )
        if job is None:
            return

        job.locked_at = now
        job.save(update_fields=['locked_at'])

        if job.phase != SummaryBackfillJob.Phase.IDLE and job.pending_tasks > 0:
            stale_before = now - timedelta(minutes=BACKFILL_BATCH_STALE_MINUTES)
            if job.phase_started_at and job.phase_started_at < stale_before:
                _backfill_restart_batch(job)
            return

        if job.phase == SummaryBackfillJob.Phase.IDLE:
            _backfill_dispatch_monitors(job)
        elif job.phase == SummaryBackfillJob.Phase.MONITORS:
            _backfill_dispatch_regions(job)
        elif job.phase == SummaryBackfillJob.Phase.REGIONS:
            _backfill_complete_chunk(job)


def _backfill_dispatch_monitors(job):
    chunk_start = chunk_start_for(job.cursor, job.range_start, job.chunk_days)
    entry_models = get_summarizable_entry_models()
    monitor_ids = monitors_with_data_in(chunk_start, job.cursor, entry_models)

    job.chunk_start = chunk_start
    job.batch_id += 1
    job.pending_tasks = len(monitor_ids)
    job.phase = SummaryBackfillJob.Phase.MONITORS
    job.phase_started_at = timezone.now()
    job.save()

    job_id = job.pk
    batch_id = job.batch_id
    chunk_end = job.cursor
    for monitor_id in monitor_ids:
        transaction.on_commit(
            lambda m=monitor_id: backfill_monitor_chunk(job_id, str(m), chunk_start, chunk_end, batch_id)
        )


def _backfill_dispatch_regions(job):
    region_ids = regions_with_monitors()

    job.batch_id += 1
    job.pending_tasks = len(region_ids)
    job.phase = SummaryBackfillJob.Phase.REGIONS
    job.phase_started_at = timezone.now()
    job.save()

    job_id = job.pk
    batch_id = job.batch_id
    chunk_start = job.chunk_start
    chunk_end = job.cursor
    for region_id in region_ids:
        transaction.on_commit(
            lambda r=region_id: backfill_region_chunk(job_id, str(r), chunk_start, chunk_end, batch_id)
        )


def _backfill_complete_chunk(job):
    days = list(iter_chunk_days(job.chunk_start, job.cursor))

    for day in days:
        target, source, window_start, window_end = daily_rollup_window(day)
        rollup_monitor_summaries(target, source, window_start, window_end)
        rollup_region_summaries(target, source, window_start, window_end)

    for day in days:
        for target, source, window_start, window_end in higher_rollup_windows(day):
            rollup_monitor_summaries(target, source, window_start, window_end)
            rollup_region_summaries(target, source, window_start, window_end)

    job.cursor = job.chunk_start
    job.chunk_start = None
    job.phase = SummaryBackfillJob.Phase.IDLE
    job.pending_tasks = 0
    job.consecutive_failures = 0
    job.last_error = ''
    if job.cursor <= job.range_start:
        job.state = SummaryBackfillJob.State.DONE
    job.save()


def _backfill_restart_batch(job):
    """
    Re-dispatch whichever phase actually stalled, without discarding a phase
    that already finished. A stall in `monitors` re-dispatches monitors; a
    stall in `regions` re-dispatches only regions — the already-completed
    monitors phase is never redone. This matters because "regions" batches
    routinely finish 99%+ before a handful of stragglers lose a priority
    race against live real-time tasks sharing the same queue; discarding an
    entire, already-successful monitors phase over that is pure waste that
    also adds unnecessary DB load at the worst possible time.
    """
    job.consecutive_failures += 1
    job.last_error = (
        f'Batch {job.batch_id} stalled in phase "{job.phase}" with '
        f'{job.pending_tasks} pending task(s); restarting the {job.phase} phase.'
    )

    if job.consecutive_failures >= BACKFILL_MAX_CONSECUTIVE_FAILURES:
        job.phase = SummaryBackfillJob.Phase.IDLE
        job.pending_tasks = 0
        job.state = SummaryBackfillJob.State.FAILED
        job.save()
        return

    if job.phase == SummaryBackfillJob.Phase.MONITORS:
        _backfill_dispatch_monitors(job)
    elif job.phase == SummaryBackfillJob.Phase.REGIONS:
        _backfill_dispatch_regions(job)


# ---- Temporary memory diagnostics ----
# For the huey_summaries memory investigation. Gated behind MEMORY_DEBUG env
# var -- a no-op otherwise, since tracemalloc.is_tracing() is False unless
# SummariesConfig.ready() started it (also gated on the same var). Remove
# once the investigation is resolved.
#
# Priority is set well above everything else on this queue (existing scheme
# tops out at 100) on purpose: we specifically want a snapshot during the
# exact moments the queue is congested and memory is climbing, not only
# when things are quiet. At priority 1 this got stuck behind the same
# backlog we're trying to diagnose.

_memory_debug_logger = logging.getLogger('camp.apps.summaries.memory_debug')


@db_periodic_task(crontab(minute='*'), priority=1000, queue='summaries')
def memory_debug_snapshot():
    if not os.environ.get('MEMORY_DEBUG'):
        return

    import tracemalloc
    if not tracemalloc.is_tracing():
        return

    current, peak = tracemalloc.get_traced_memory()
    snapshot = tracemalloc.take_snapshot()
    top_stats = snapshot.statistics('lineno')[:15]

    lines = [f'MEMORY_DEBUG snapshot: current={current / 1024 / 1024:.1f}MB peak={peak / 1024 / 1024:.1f}MB']
    for stat in top_stats:
        lines.append(f'  {stat}')
    _memory_debug_logger.warning('\n'.join(lines))
