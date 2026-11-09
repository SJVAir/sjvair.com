import logging
import time
from datetime import timedelta
from itertools import groupby

from django.db import transaction
from django.db.models import Exists, F, OuterRef, Q
from django.utils import timezone

from django_huey import db_task, db_periodic_task
from huey import crontab

from camp.apps.entries.fields import EntryTypeField
from camp.apps.entries.stages import Stage
from camp.apps.monitors.models import Monitor
from camp.apps.regions.models import Region
from camp.apps.summaries.periods import iter_hours, period_end, period_start
from camp.apps.summaries.schedule import HOURLY_FIRE_MINUTE, LATE_RUN_WARNING, hour_for_run, pacific_crontab
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
from camp.apps.summaries.peaks import fill_daily_peaks, peak_entry_models
from camp.apps.summaries.selection import (
    monitor_summary_entry_models,
    monitor_types_summarizing,
    region_summary_entry_models,
    switch_entry_models,
)

logger = logging.getLogger('camp.apps.summaries')


# ---- Hourly tasks ----

def _scheduled_hour(kind):
    """The hour an hourly parent was scheduled to summarize; warns if it started late."""
    fire_minute = HOURLY_FIRE_MINUTE[kind]
    hour, lateness = hour_for_run(fire_minute, timezone.now())
    if lateness > LATE_RUN_WARNING:
        logger.warning(
            '%s started %s after its :%02d run; summarizing %s',
            kind, lateness, fire_minute, hour,
        )
    return hour

# Hourly summaries run late in the hour (:45/:50) rather than right after it
# closes, so the previous hour has ~45 min to settle first: late-arriving
# upstream batches (VOZbox lands ~:10, AirNow/AQView/CIMIS can lag longer)
# and the hourly health checks (:40, camp/apps/qaqc/tasks.py) that weight
# LCS monitors in the region summaries. The daily and longer rollups start
# at 01:00 Pacific so yesterday's final hour (summarized at 00:45) is in place.
#
# Huey crontabs run in UTC (its utc=True default; DJANGO_HUEY doesn't change
# it), so those rollups use schedule.pacific_crontab: it matches both UTC
# hours that can hold 01:00 (or 02:00) Pacific and keeps the one that is the
# Pacific hour. The decision is made when the scheduler enqueues the task, so
# a rollup that starts late (queued behind the hourly fan-outs) still runs.
#
# The hourly parents pick their hour from the schedule (schedule.hour_for_run),
# not from the clock when they run, and sit above their children (110 and 105
# over 100 and 90) so they start before the children they enqueue: the region
# parent can't queue behind every pending monitor child and wake up an hour
# late. A parent that still starts late logs a warning.
#
# Task priorities decrease with dependency depth so upstream data is always
# ready before downstream aggregations consume it:
#   hourly monitor parent (110) → hourly region parent (105)
#   → hourly monitor (100) → hourly region (90) → daily monitor (80) → daily region (70)
#   → monthly monitor (60) → monthly region (50) → quarterly monitor (40) → quarterly region (30)
#   → seasonal monitor (20) → seasonal region (15) → yearly monitor (10) → yearly region (5)

@db_periodic_task(crontab(hour='*', minute='45'), priority=110, queue='summaries')
def hourly_monitor_summaries(hour=None):
    """
    Compute hourly MonitorSummary for every (monitor, entry_type, processor) combo
    that has entries in the previous hour. Only RAW (processor='') and CALIBRATED
    (processor≠'') entries are summarized — CORRECTED and CLEANED are skipped.

    Only the region types: types a monitor type opts into through its
    ENTRY_CONFIG (CIMIS weather) are summarized by that monitor's ingest.
    """
    if hour is None:
        hour = _scheduled_hour('monitor')

    for EntryModel in region_summary_entry_models():
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


@db_periodic_task(crontab(hour='*', minute='50'), priority=105, queue='summaries')
def hourly_region_summaries(hour=None):
    """
    Compute one hourly RegionSummary per region per entry_type found in
    MonitorSummary records for that hour. Uses each monitor's best available
    calibration — no processor fan-out needed at the region level.

    Must stay scheduled after hourly_health_checks (camp/apps/qaqc/tasks.py)
    has scored the hour -- the region weighting treats a monitor with no
    HealthCheck row as fully healthy, so running before the checks land
    over-weights bad sensors.
    """
    if hour is None:
        hour = _scheduled_hour('region')

    entry_models = region_summary_entry_models()

    region_ids = (Region.objects
        .filter(
            Exists(
                Monitor.objects.filter(
                    position__isnull=False,
                    position__intersects=OuterRef('boundary__geometry'),
                )
            ),
            boundary__isnull=False
        )
        .values_list('pk', flat=True)
    )

    for region_id in region_ids:
        for EntryModel in entry_models:
            summarize_region_hour(str(region_id), hour, EntryModel.entry_type)


@db_task(priority=90, queue='summaries')
def summarize_region_hour(region_id, hour, entry_type):
    """Compute and save one hourly RegionSummary record."""
    region = Region.all_objects.select_related('boundary').get(pk=region_id)

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


# ---- On-arrival summaries (CIMIS weather) ----
#
# CIMIS readings often land hours late, after the :45 parent has moved on
# (and that parent skips weather types anyway). Each CIMIS import summarizes
# the hours it wrote, and its daily finalize re-pull re-summarizes yesterday.

def rollup_windows_for(hours, now):
    """
    {resolution: [period starts]} holding `hours`, for each resolution above
    hourly, keeping only periods that have ended by `now`. No widening: only
    the periods the hours fall in.
    """
    from camp.apps.summaries.repair import RESOLUTIONS

    windows = {}
    for resolution in RESOLUTIONS:
        starts = {period_start(resolution, hour) for hour in hours}
        windows[resolution] = sorted(s for s in starts if period_end(resolution, s) <= now)
    return windows


@db_task(priority=100, queue='summaries')
def summarize_monitor_hours(monitor_id, hours):
    """
    Summarize one monitor's `hours` (hour starts, spanning at most 2 days) and
    re-roll the finished periods holding them. Only for monitor types with
    their own summarized types (CIMIS); monitor rows only, never region rows.
    """
    from camp.apps.summaries.repair import reroll

    if not hours:
        return
    monitor = Monitor.objects.get(pk=monitor_id)
    entry_models = monitor_summary_entry_models(monitor)
    if not set(entry_models) & set(switch_entry_models()):
        return

    now = timezone.now()
    start = min(hours)
    end = max(hours) + timedelta(hours=1)
    backfill_monitor_hours(monitor, start, end, entry_models)
    reroll('monitor', [monitor.pk], start, end, now, windows=rollup_windows_for(hours, now))


# ---- Rollup helpers ----

def rollup_monitor_summaries(target_resolution, source_resolution, window_start, window_end, monitor_ids=None):
    """
    Roll up MonitorSummary records from source_resolution into target_resolution
    for the given time window.

    Streams source records ordered by (monitor, entry_type, processor) and groups
    them via itertools.groupby, rather than materializing the whole window into
    one list first. Matters for QUARTERLY/SEASONAL/YEARLY, which can span every
    monitor's records for the period at once, each carrying a full tdigest blob -
    this keeps peak memory to one group (bounded by periods-per-window) instead of
    the whole window (monitors × entry_types × processors × periods).

    Optionally scoped to a list of monitor_ids (for targeted backfill/recalculation).
    """
    qs = MonitorSummary.objects.filter(
        resolution=source_resolution,
        timestamp__gte=window_start,
        timestamp__lt=window_end,
    )
    if monitor_ids is not None:
        qs = qs.filter(monitor_id__in=monitor_ids)

    rows = qs.order_by('monitor_id', 'entry_type', 'processor').values(
        'monitor_id', 'entry_type', 'processor',
        'count', 'expected_count', 'sum_value', 'sum_of_squares',
        'minimum', 'maximum', 'tdigest',
    ).iterator()

    to_upsert = []
    for (monitor_id, entry_type, processor), group in groupby(
        rows, key=lambda r: (r['monitor_id'], r['entry_type'], r['processor'])
    ):
        stats = rollup_summaries(list(group))
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
        # The peaks aren't in update_fields, so the upsert keeps them; the fill rewrites them.
        if target_resolution == BaseSummary.Resolution.DAILY:
            fill_daily_peaks('monitor', monitor_ids, window_start, window_end)


def rollup_region_summaries(target_resolution, source_resolution, window_start, window_end, region_ids=None):
    """Same as rollup_monitor_summaries but for RegionSummary."""
    qs = RegionSummary.objects.filter(
        resolution=source_resolution,
        timestamp__gte=window_start,
        timestamp__lt=window_end,
    )
    if region_ids is not None:
        qs = qs.filter(region_id__in=region_ids)

    rows = qs.order_by('region_id', 'entry_type').values(
        'region_id', 'entry_type', 'station_count',
        'count', 'weight', 'expected_count', 'sum_value', 'sum_of_squares',
        'minimum', 'maximum', 'tdigest',
    ).iterator()

    to_upsert = []
    for (region_id, entry_type), group in groupby(rows, key=lambda r: (r['region_id'], r['entry_type'])):
        group_records = list(group)
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
        # The peaks aren't in update_fields, so the upsert keeps them; the fill rewrites them.
        if target_resolution == BaseSummary.Resolution.DAILY:
            fill_daily_peaks('region', region_ids, window_start, window_end)


# ---- Rollup periodic tasks ----

def _previous_period_start(resolution, now=None):
    """Start of the period before the one containing `now` (default: the current time)."""
    now = now or timezone.now()
    return period_start(resolution, period_start(resolution, now) - timedelta(microseconds=1))


def _rollup_monitors(target, source, resolution, start):
    start = start or _previous_period_start(resolution)
    rollup_monitor_summaries(target, source, start, period_end(resolution, start))


def _rollup_regions(target, source, resolution, start):
    start = start or _previous_period_start(resolution)
    rollup_region_summaries(target, source, start, period_end(resolution, start))


R = BaseSummary.Resolution


def _refresh_previous_max_8h(kind, start):
    """
    The 8-hour windows starting late in a day reach into the next morning, so
    that day's daily rollup stores a provisional `max_8h`. Run with the next
    day's rollup, this recomputes the previous day's, now that the hours exist.
    `start` is the day just rolled up.
    """
    models = [model for model, field in peak_entry_models().items() if field == 'max_8h']
    fill_daily_peaks(
        kind, None, _previous_period_start('day', start), start,
        entry_models=models, fields=('max_8h',),
    )


@db_periodic_task(pacific_crontab(1, '0'), priority=80, queue='summaries')
def daily_monitor_summaries(day=None):
    """Roll up yesterday's hourly MonitorSummary records into daily ones."""
    day = day or _previous_period_start('day')
    _rollup_monitors(R.DAILY, R.HOURLY, 'day', day)
    _refresh_previous_max_8h('monitor', day)


@db_periodic_task(pacific_crontab(1, '10'), priority=70, queue='summaries')
def daily_region_summaries(day=None):
    """Roll up yesterday's hourly RegionSummary records into daily ones."""
    day = day or _previous_period_start('day')
    _rollup_regions(R.DAILY, R.HOURLY, 'day', day)
    _refresh_previous_max_8h('region', day)


@db_periodic_task(pacific_crontab(1, '15', day='1'), priority=60, queue='summaries')
def monthly_monitor_summaries(month_start=None):
    """Roll up last month's daily MonitorSummary records into monthly ones."""
    _rollup_monitors(R.MONTHLY, R.DAILY, 'month', month_start)


@db_periodic_task(pacific_crontab(1, '25', day='1'), priority=50, queue='summaries')
def monthly_region_summaries(month_start=None):
    """Roll up last month's daily RegionSummary records into monthly ones."""
    _rollup_regions(R.MONTHLY, R.DAILY, 'month', month_start)


@db_periodic_task(pacific_crontab(1, '30', month='1,4,7,10', day='1'), priority=40, queue='summaries')
def quarterly_monitor_summaries(quarter_start=None):
    """Roll up last quarter's monthly MonitorSummary records into quarterly ones."""
    _rollup_monitors(R.QUARTERLY, R.MONTHLY, 'quarter', quarter_start)


@db_periodic_task(pacific_crontab(1, '35', month='1,4,7,10', day='1'), priority=30, queue='summaries')
def quarterly_region_summaries(quarter_start=None):
    """Roll up last quarter's monthly RegionSummary records into quarterly ones."""
    _rollup_regions(R.QUARTERLY, R.MONTHLY, 'quarter', quarter_start)


@db_periodic_task(pacific_crontab(1, '45', month='3,6,9,12', day='1'), priority=20, queue='summaries')
def seasonal_monitor_summaries(season_start=None):
    """
    Roll up the past 3 months of monthly MonitorSummary records into a seasonal one.
    Runs Mar 1, Jun 1, Sep 1, Dec 1 to summarize the just-completed season.
    """
    _rollup_monitors(R.SEASONAL, R.MONTHLY, 'season', season_start)


@db_periodic_task(pacific_crontab(1, '55', month='3,6,9,12', day='1'), priority=15, queue='summaries')
def seasonal_region_summaries(season_start=None):
    """Roll up the past 3 months of monthly RegionSummary records into a seasonal one."""
    _rollup_regions(R.SEASONAL, R.MONTHLY, 'season', season_start)


@db_periodic_task(pacific_crontab(2, '0', month='1', day='1'), priority=10, queue='summaries')
def yearly_monitor_summaries(year_start=None):
    """Roll up last year's monthly MonitorSummary records into yearly ones."""
    _rollup_monitors(R.YEARLY, R.MONTHLY, 'year', year_start)


@db_periodic_task(pacific_crontab(2, '5', month='1', day='1'), priority=5, queue='summaries')
def yearly_region_summaries(year_start=None):
    """Roll up last year's monthly RegionSummary records into yearly ones."""
    _rollup_regions(R.YEARLY, R.MONTHLY, 'year', year_start)


# ---- Backfill ----

@db_task(priority=1, queue='summaries')
def backfill_monitor_chunk(job_id, monitor_id, chunk_start, chunk_end, batch_id):
    """Compute one monitor's hourly summaries for a backfill chunk, then report completion."""
    monitor = Monitor.objects.get(pk=monitor_id)
    entry_models = monitor_summary_entry_models(monitor)
    backfill_monitor_hours(monitor, chunk_start, chunk_end, entry_models)

    SummaryBackfillJob.objects.filter(
        pk=job_id, batch_id=batch_id, phase=SummaryBackfillJob.Phase.MONITORS,
    ).update(pending_tasks=F('pending_tasks') - 1)


@db_task(priority=1, queue='summaries')
def backfill_region_chunk(job_id, region_id, chunk_start, chunk_end, batch_id):
    """Compute one region's hourly summaries for a backfill chunk, then report completion."""
    region = Region.all_objects.select_related('boundary').get(pk=region_id)
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
    # Switch types (CIMIS weather) are checked only on the monitor types that switch them on.
    monitor_ids = monitors_with_data_in(
        chunk_start, job.cursor, region_summary_entry_models(),
        scoped_entry_models={m: monitor_types_summarizing(m) for m in switch_entry_models()},
    )

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


# ---- Integrity check ----

INTEGRITY_LOOKBACK = timedelta(days=400)


@db_periodic_task(pacific_crontab(2, '30'), priority=1, queue='summaries')
def check_summary_integrity(now=None):
    """
    Count, and log as an error (Sentry captures it), two kinds of damage:

    - summary rows whose timestamp isn't a Pacific period start, in either
      table, over the last 400 days;
    - hours of the previous Pacific day with monitor hourly summaries but no
      region hourly summaries at all.

    Read-only. The hour check is two bounded distinct-timestamp queries, not
    a per-region geo check. Logs how long the run took at info level, so the
    400-day scan's cost shows in production logs.
    """
    from camp.apps.summaries.repair import find_misaligned  # repair imports this module

    now = now or timezone.now()
    start = now - INTEGRITY_LOOKBACK
    began = time.monotonic()

    misaligned = 0
    for model, ids_field in ((MonitorSummary, 'monitor_id'), (RegionSummary, 'region_id')):
        found = find_misaligned(model, ids_field, None, start, now)
        misaligned += sum(len(timestamps) for timestamps in found.values())
    scanned = time.monotonic()

    today = period_start('day', now)
    yesterday = period_start('day', today - timedelta(hours=1))

    def hour_timestamps(queryset):
        return set(
            queryset.filter(
                resolution=BaseSummary.Resolution.HOURLY,
                timestamp__gte=yesterday,
                timestamp__lt=today,
            ).values_list('timestamp', flat=True).distinct().order_by()
        )

    # Only the region types: weather types have monitor rows and never region rows.
    region_types = [m.entry_type for m in region_summary_entry_models()]
    monitor_hours = hour_timestamps(MonitorSummary.objects.filter(entry_type__in=region_types))
    region_hours = hour_timestamps(RegionSummary.objects.all())
    missing = [hour for hour in iter_hours(yesterday, today) if hour in monitor_hours and hour not in region_hours]

    result = {'misaligned': misaligned, 'missing_region_hours': len(missing)}
    logger.info(
        'Summary integrity check took %.1fs (misaligned scan %.1fs, region hours %.1fs)',
        time.monotonic() - began, scanned - began, time.monotonic() - scanned,
    )
    if misaligned or missing:
        logger.error(
            'Summary integrity check found %d misaligned row timestamp(s) and %d hour(s) '
            'with monitor but no region summaries (%s): %s',
            misaligned, len(missing), yesterday.date(), ', '.join(h.isoformat() for h in missing),
        )
    return result
