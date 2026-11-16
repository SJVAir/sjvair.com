import logging
import time

from datetime import datetime, timedelta, timezone as dt_timezone

from django.conf import settings
from django.contrib.gis.geos import Point
from django.db import transaction
from django.db.models import F, Q
from django.utils import timezone

from django_huey import db_task, db_periodic_task
from huey import crontab

from camp.apps.monitors.legacy_backfill import NEAR_DUPLICATE_WINDOW, _has_near, chunk_start_for
from camp.apps.monitors.purpleair.api import (
    PurpleAirAPIError, PurpleAirNotFound, PurpleAirRateLimited, purpleair_api,
)
from camp.apps.monitors.purpleair.history import existing_raw_timestamps, monitors_for_window
from camp.apps.monitors.purpleair.models import PurpleAir, PurpleAirHistoryGap, PurpleAirHistoryJob
from camp.apps.monitors.tasks import _fail_job, _insert_raw_entries, _is_stalled
from camp.apps.regions.models import Region
from camp.utils import gis

logger = logging.getLogger(__name__)


@db_periodic_task(crontab(minute='*'), priority=50)
def update_realtime():
    start = timezone.now()
    print(f'\n=== PurpleAir Import Start: {start.time()}\n')

    seen_ids = []
    sensors = purpleair_api.list_group_members(settings.PURPLEAIR_GROUP_ID)
    for sensor in sensors:
        seen_ids.append(sensor['sensor_index'])
        # process_data.call_local(sensor)
        process_data.schedule([sensor], delay=1, priority=40)

    # Any monitors that are active but missing
    # from the group should be manually retried.
    missing_monitors = (PurpleAir.objects
        .exclude(sensor_id__in=seen_ids)
        .get_active()
    )

    for monitor in missing_monitors:
        monitor.import_latest()

    end = timezone.now()
    print(f'\n=== PurpleAir Import Done: {start.time()} - {end.time()} ({end - start})\n')


@db_periodic_task(crontab(hour='23', minute='0'))
def update_monitor_data():
    sensors = purpleair_api.list_group_members(settings.PURPLEAIR_GROUP_ID)
    for sensor in sensors:
        try:
            monitor = PurpleAir.objects.get(sensor_id=sensor['sensor_index'])
        except PurpleAir.DoesNotExist:
            monitor = PurpleAir(sensor_id=sensor['sensor_index'])

        data = purpleair_api.get_sensor(monitor.sensor_id)
        if data is None:
            purpleair_api.delete_group_member(settings.PURPLEAIR_GROUP_ID, monitor.sensor_id)
            continue

        monitor.update_data(data)
        monitor.save()


@db_periodic_task(crontab(hour='23', minute='30'))
def find_new_monitors():
    members = {
        member['sensor_index'] for member in
        purpleair_api.get_group(settings.PURPLEAIR_GROUP_ID)['members']
    }

    counties = Region.objects.counties().combined_geometry()
    nwlng, selat, selng, nwlat = counties.extent

    monitors = purpleair_api.list_sensors(
        fields=['sensor_index', 'name', 'longitude', 'latitude'],
        nwlng=nwlng,
        selat=selat,
        selng=selng,
        nwlat=nwlat,
    )

    print('Total monitors from PurpleAir:', len(monitors))
    print('Number of monitors in our group:', len(members))

    for monitor in monitors:
        lat = monitor.get('latitude')
        lon = monitor.get('longitude')

        # Skip if there's no lat/lon.
        if lat is None or lon is None:
            continue

        # Skip if we already have it.
        if monitor['sensor_index'] in members:
            continue

        # Skip monitors outside the geographic boundaries.
        point = Point(lon, lat, srid=gis.EPSG_LATLON)
        if not counties.contains(point):
            continue

        # All we need to do is add it to the group within PurpleAir,
        # and we'll pick it up on the next import pass.
        print(f'Adding #{monitor["sensor_index"]} - {monitor["name"]}')
        purpleair_api.create_group_member(
            settings.PURPLEAIR_GROUP_ID,
            monitor['sensor_index']
        )


@db_task()
def process_data(payload, cutoff_stage=None):
    try:
        monitor = PurpleAir.objects.get(sensor_id=payload['sensor_index'])
    except PurpleAir.DoesNotExist:
        data = purpleair_api.get_sensor(payload['sensor_index'])
        if data is None:
            purpleair_api.delete_group_member(settings.PURPLEAIR_GROUP_ID, payload['sensor_index'])
            return

        monitor = PurpleAir(sensor_id=payload['sensor_index'])
        monitor.update_data(data)
        monitor.save()

    entries = monitor.create_entries(payload)
    for entry in entries:
        monitor.process_entry_pipeline(entry, cutoff_stage=cutoff_stage)


    # Legacy
    # Commented out, to be removed in the future.
    # entries = monitor.create_entries_legacy(payload)
    # for entry in entries:
    #     monitor.check_latest(entry)

    monitor.save()


# History import (PurpleAirHistoryJob). See
# docs/superpowers/specs/2026-10-22-purpleair-history-import-design.md.

HISTORY_RATE_LIMIT_BACKOFF = (5, 15, 45)  # seconds before each retry of the same request
HISTORY_MAX_FOLLOWUPS = 3
HISTORY_SHORT_SECONDS = 3600
HISTORY_INSERT_BATCH = 5000

HISTORY_LOCK_STALE_SECONDS = 30
HISTORY_BATCH_STALE_MINUTES = 60
HISTORY_MAX_CONSECUTIVE_FAILURES = 5


def _history_request(monitor, start, end, stats):
    for delay in (*HISTORY_RATE_LIMIT_BACKOFF, None):
        stats['requests'] += 1
        try:
            return purpleair_api.get_sensor_history_window(monitor.sensor_id, start, end)
        except PurpleAirRateLimited:
            if delay is None:
                raise
            time.sleep(delay)


def _history_fetch(monitor, start, end, stats):
    '''
    Returns (rows, gap) where gap is None or a (reason, message) tuple. Rows
    fetched before an error are still returned so they get stored.
    '''
    rows = []
    try:
        rows = _history_request(monitor, start, end, stats)
        short_before = end.timestamp() - HISTORY_SHORT_SECONDS
        for _ in range(HISTORY_MAX_FOLLOWUPS):
            if not rows or rows[-1]['time_stamp'] >= short_before:
                return rows, None
            more = _history_request(
                monitor, datetime.fromtimestamp(rows[-1]['time_stamp'] + 1, tz=dt_timezone.utc), end, stats,
            )
            if not more:
                return rows, None  # the sensor really stopped reporting
            rows = rows + more
        if rows[-1]['time_stamp'] < short_before:
            return rows, (PurpleAirHistoryGap.Reason.TRUNCATED, 'Response still short after follow-up requests.')
        return rows, None
    except PurpleAirNotFound as error:
        return rows, (PurpleAirHistoryGap.Reason.NOT_FOUND, str(error))
    except PurpleAirAPIError as error:
        return rows, (PurpleAirHistoryGap.Reason.ERROR, str(error))


def _history_store(monitor, rows, start, end):
    '''
    Builds entries for the rows (no per-entry queries), drops those with an
    existing RAW row within NEAR_DUPLICATE_WINDOW, and bulk-inserts the rest.
    Returns the number inserted.
    '''
    by_model = {}
    for payload in rows:
        for entry in monitor.create_entries(payload, save=False, validate=False):
            by_model.setdefault(type(entry), []).append(entry)

    created = 0
    for entry_model, entries in by_model.items():
        existing = existing_raw_timestamps(monitor, entry_model, start, end, NEAR_DUPLICATE_WINDOW)
        seen = set()
        missing = []
        for entry in entries:
            key = (entry.timestamp, entry.sensor)
            if key in seen or _has_near(existing.get(entry.sensor, ()), entry.timestamp):
                continue
            seen.add(key)
            missing.append(entry)
        for i in range(0, len(missing), HISTORY_INSERT_BATCH):
            created += _insert_raw_entries(entry_model, missing[i:i + HISTORY_INSERT_BATCH])
    return created


@db_task(priority=1, queue='secondary')
def import_purpleair_history_chunk(job_id, monitor_id, start, end, batch_id=None):
    '''
    Import one monitor's history for [start, end) from the PurpleAir API as
    RAW entries, then report to the job. batch_id=None (used by `retry`) means
    the task isn't part of a tracked batch: counters update, pending_tasks
    doesn't.
    '''
    stats = {'requests': 0, 'rows': 0, 'created': 0, 'points': 0}
    monitor = PurpleAir.objects.filter(pk=monitor_id, sensor_id__isnull=False).first()
    if monitor is None:
        logger.warning('PurpleAir history: monitor %s no longer exists; skipping.', monitor_id)
    else:
        rows, gap = _history_fetch(monitor, start, end, stats)
        stats['rows'] = len(rows)
        stats['points'] = sum(
            1 for row in rows for field in purpleair_api.HISTORY_FIELDS if row.get(field) is not None
        )
        if rows:
            stats['created'] = _history_store(monitor, rows, start, end)
        if gap is not None and PurpleAirHistoryJob.objects.filter(pk=job_id).exists():
            reason, message = gap
            PurpleAirHistoryGap.objects.update_or_create(
                job_id=job_id, monitor=monitor, window_start=start, window_end=end,
                defaults={'reason': reason, 'message': message},
            )

    jobs = PurpleAirHistoryJob.objects.filter(pk=job_id)
    updates = {
        'requests_made': F('requests_made') + stats['requests'],
        'rows_fetched': F('rows_fetched') + stats['rows'],
        'raw_entries_created': F('raw_entries_created') + stats['created'],
        'data_points': F('data_points') + stats['points'],
        'last_progress_at': timezone.now(),
    }
    if batch_id is not None:
        jobs = jobs.filter(batch_id=batch_id)
        updates['pending_tasks'] = F('pending_tasks') - 1
    jobs.update(**updates)


@db_periodic_task(crontab(minute='*'), priority=1, queue='secondary')
def import_purpleair_history_tick():
    '''
    Drive one step of the active PurpleAirHistoryJob, if any. Never blocks on
    the sub-tasks it dispatches. Mirrors backfill_legacy_entries_tick.
    '''
    now = timezone.now()

    with transaction.atomic():
        job = (
            PurpleAirHistoryJob.objects
            .select_for_update(skip_locked=True)
            .filter(state=PurpleAirHistoryJob.State.RUNNING)
            .filter(
                Q(locked_at__isnull=True) |
                Q(locked_at__lt=now - timedelta(seconds=HISTORY_LOCK_STALE_SECONDS))
            )
            .order_by('created')
            .first()
        )
        if job is None:
            return

        job.locked_at = now
        job.save(update_fields=['locked_at'])

        if job.pending_tasks > 0:
            stale_before = now - timedelta(minutes=HISTORY_BATCH_STALE_MINUTES)
            if _is_stalled(job, stale_before):
                _history_restart_batch(job)
            return

        if job.chunk_start is not None:
            _history_complete_chunk(job)
        else:
            job.chunk_start = chunk_start_for(job.cursor, job.range_start, job.chunk_days)
            if job.consecutive_failures >= HISTORY_MAX_CONSECUTIVE_FAILURES:
                job.consecutive_failures = 0  # resumed after FAILED: fresh retry budget
            _history_dispatch(job)


def _history_dispatch(job):
    monitor_ids = monitors_for_window(job.chunk_start, job.cursor, job.monitor_ids)

    job.batch_id += 1
    job.pending_tasks = len(monitor_ids)
    job.phase_started_at = timezone.now()
    job.save()

    job_id = job.pk
    batch_id = job.batch_id
    chunk_start = job.chunk_start
    chunk_end = job.cursor
    for monitor_id in monitor_ids:
        transaction.on_commit(
            lambda m=monitor_id: import_purpleair_history_chunk(job_id, str(m), chunk_start, chunk_end, batch_id)
        )


def _history_complete_chunk(job):
    job.cursor = job.chunk_start
    job.chunk_start = None
    job.pending_tasks = 0
    job.consecutive_failures = 0
    job.last_error = ''
    if job.cursor <= job.range_start:
        job.state = PurpleAirHistoryJob.State.DONE
    job.save()


def _history_restart_batch(job):
    job.consecutive_failures += 1
    job.last_error = (
        f'Batch {job.batch_id} stalled with {job.pending_tasks} pending task(s); restarting.'
    )

    if job.consecutive_failures >= HISTORY_MAX_CONSECUTIVE_FAILURES:
        _fail_job(job, 'PurpleAir history import', 'import_purpleair_history')
        return

    _history_dispatch(job)
