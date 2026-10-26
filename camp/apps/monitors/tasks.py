import logging

from datetime import timedelta

from django.conf import settings
from django.core.mail import mail_admins, send_mail
from django.db import DatabaseError, transaction
from django.db.models import F, Q
from django.template.loader import render_to_string
from django.utils import timezone

from django_huey import db_task, db_periodic_task
from huey import crontab

from camp.utils.text import render_markdown
from camp.apps.monitors.legacy_backfill import (
    LEGACY_BACKFILL_MAP, chunk_start_for, chunk_end_for, find_missing_raw_entries,
    monitors_with_legacy_data_in, find_incomplete_pipelines, pipeline_entry_models,
    monitors_with_incomplete_pipelines_in,
)
from camp.apps.calibrations.lookup import ChunkCalibrationLookup
from camp.apps.entries.models.base import reuse_monitor
from .models import Entry, EntryBackfillJob, Monitor, PipelineBackfillJob

logger = logging.getLogger(__name__)


# @db_periodic_task(crontab(hour='13', minute='0'), priority=100)
# def check_monitor_status():
#     # Update to run daily – monitors that have been offline for 24-48 hours
#     inactive_monitors = {}
#     upper_bound = timezone.now() - timedelta(hours=24)
#     lower_bound = timezone.now() - timedelta(hours=48)

#     for subclass in Monitor.subclasses():
#         SubMonitor = getattr(Monitor, subclass).related.related_model
#         inactive_monitors[SubMonitor.__name__] = list((SubMonitor.objects
#             .filter(latest__timestamp__range=(lower_bound, upper_bound))
#             .select_related('latest')
#         ))

#         print(SubMonitor.__name__, lower_bound, upper_bound, len(inactive_monitors[SubMonitor.__name__]))

#     # Filter out devices with no new inactivity.
#     inactive_monitors = {k: v for k, v in inactive_monitors.items() if len(v)}

#     if any([len(ml) >= 0 for ml in inactive_monitors.values()]):
#         total_inactive = sum([len(ml) for ml in inactive_monitors.values()])
#         message = render_to_string('email/monitor-alerts.md', {
#             'inactive_monitors': inactive_monitors,
#             'total_inactive': total_inactive
#         })

#         print(message)
#         send_mail(
#             subject=f'[Monitor Inactivity] {total_inactive} New Inactive Monitors',
#             message=message,
#             html_message=render_markdown(message),
#             recipient_list=settings.SJVAIR_INACTIVE_ALERT_EMAILS,
#             from_email=None,
#         )


@db_task(queue='secondary')
def recalibrate_entry(entry_id):
    entry = Entry.objects.get(pk=entry_id)
    entry.calibrate_pm25()
    entry.pm25_avg_15 = entry.get_average('pm25', 15)
    entry.pm25_avg_60 = entry.get_average('pm25', 60)
    entry.save()


@db_task(priority=1, queue='secondary')
def backfill_monitor_chunk(job_id, monitor_id, chunk_start, chunk_end, batch_id):
    '''
    For one monitor, insert any RAW entries missing in [chunk_start, chunk_end)
    across its LEGACY_BACKFILL_MAP-configured entry types, then report completion.
    A monitor that no longer exists counts as done; a row the new tables can't
    hold (e.g. a value too large for the field) is logged and skipped.
    '''
    created_count = 0
    try:
        monitor = _resolve_monitor_subclass(monitor_id)
    except Monitor.DoesNotExist:
        logger.warning('Legacy backfill: monitor %s no longer exists; skipping.', monitor_id)
        monitor = None

    if monitor is not None:
        for entry_model, mapping in LEGACY_BACKFILL_MAP.get(type(monitor), {}).items():
            missing = find_missing_raw_entries(monitor, entry_model, mapping, chunk_start, chunk_end)
            if missing:
                created_count += _insert_raw_entries(entry_model, missing)

    EntryBackfillJob.objects.filter(
        pk=job_id, batch_id=batch_id,
    ).update(
        pending_tasks=F('pending_tasks') - 1,
        raw_entries_created=F('raw_entries_created') + created_count,
        last_progress_at=timezone.now(),
    )


def _insert_raw_entries(entry_model, entries):
    '''
    Bulk-insert, falling back to one row at a time if the batch fails, so a
    single bad legacy value doesn't block the rest of the chunk. Returns the
    number of rows attempted without error (conflicts are ignored, so this
    can overcount rows that already existed).
    '''
    try:
        with transaction.atomic():
            entry_model.objects.bulk_create(entries, ignore_conflicts=True)
        return len(entries)
    except DatabaseError:
        pass

    inserted = 0
    for entry in entries:
        try:
            with transaction.atomic():
                entry_model.objects.bulk_create([entry], ignore_conflicts=True)
            inserted += 1
        except DatabaseError as error:
            logger.warning(
                'Legacy backfill: skipping %s for monitor %s at %s (sensor %r): %s',
                entry_model.__name__, entry.monitor_id, entry.timestamp, entry.sensor, error,
            )
    return inserted


@db_task(priority=1, queue='secondary')
def reprocess_monitor_chunk(job_id, monitor_id, chunk_start, chunk_end, batch_id, stop_before=''):
    '''
    For one monitor, continue the pipeline for every entry in
    [chunk_start, chunk_end) that find_incomplete_pipelines picks up (any
    stage with a processor configured and no derived entries yet), then
    report completion. Safe to re-run (see the BaseProcessor.run()
    idempotency fix).

    `stop_before` is a stage value; the pipeline stops before producing it
    (see PipelineBackfillJob.stop_before).

    A chunk reuses one monitor instance for every entry, resolves
    calibrations once per (type, trainer, position), and moves LatestEntry
    once per series at the end instead of once per entry.
    '''
    processed_count = 0
    try:
        monitor = _resolve_monitor_subclass(monitor_id)
    except Monitor.DoesNotExist:
        logger.warning('Legacy pipeline: monitor %s no longer exists; skipping.', monitor_id)
        monitor = None

    if monitor is not None:
        lookup = ChunkCalibrationLookup(chunk_end)
        with reuse_monitor(monitor), lookup.activate(), monitor.deferred_latest_entries() as latest:
            for entry_model in pipeline_entry_models(type(monitor)).keys():
                incomplete = find_incomplete_pipelines(
                    monitor, entry_model, chunk_start, chunk_end, stop_before,
                )
                for entry in incomplete:
                    entry.monitor = monitor
                    # One entry failing (bad data, or an IntegrityError from racing
                    # another worker on the same entry) shouldn't stall the batch.
                    try:
                        with transaction.atomic():
                            monitor.process_entry_pipeline(entry, stop_before or None)
                    except Exception:
                        latest.discard()
                        logger.exception(
                            'Legacy pipeline: failed to process %s %s for monitor %s',
                            entry_model.__name__, entry.pk, monitor_id,
                        )
                        continue
                    latest.commit()
                    processed_count += 1

    PipelineBackfillJob.objects.filter(
        pk=job_id, batch_id=batch_id,
    ).update(
        pending_tasks=F('pending_tasks') - 1,
        entries_processed=F('entries_processed') + processed_count,
        last_progress_at=timezone.now(),
    )


def _resolve_monitor_subclass(monitor_id):
    '''
    Monitor is base-table multi-table inheritance; find which of the
    LEGACY_BACKFILL_MAP-eligible concrete subclasses this id belongs to.
    '''
    from camp.apps.monitors.legacy_backfill import eligible_monitor_classes

    for monitor_cls in eligible_monitor_classes():
        monitor = monitor_cls.objects.filter(pk=monitor_id).first()
        if monitor is not None:
            return monitor
    raise Monitor.DoesNotExist(f'No eligible monitor subclass found for id={monitor_id}')


ENTRY_BACKFILL_LOCK_STALE_SECONDS = 30
ENTRY_BACKFILL_BATCH_STALE_MINUTES = 60
ENTRY_BACKFILL_MAX_CONSECUTIVE_FAILURES = 5


@db_periodic_task(crontab(minute='*'), priority=1, queue='secondary')
def backfill_legacy_entries_tick():
    '''
    Drive one step of the active EntryBackfillJob, if any. Never blocks on the
    sub-tasks it dispatches. See
    docs/superpowers/specs/2026-07-28-legacy-entries-backfill-design.md.
    '''
    now = timezone.now()

    with transaction.atomic():
        job = (
            EntryBackfillJob.objects
            .select_for_update(skip_locked=True)
            .filter(state=EntryBackfillJob.State.RUNNING)
            .filter(
                Q(locked_at__isnull=True) |
                Q(locked_at__lt=now - timedelta(seconds=ENTRY_BACKFILL_LOCK_STALE_SECONDS))
            )
            .order_by('created')
            .first()
        )
        if job is None:
            return

        job.locked_at = now
        job.save(update_fields=['locked_at'])

        if job.pending_tasks > 0:
            stale_before = now - timedelta(minutes=ENTRY_BACKFILL_BATCH_STALE_MINUTES)
            if _is_stalled(job, stale_before):
                _entry_backfill_restart_batch(job)
            return

        if job.chunk_start is not None:
            _entry_backfill_complete_chunk(job)
        else:
            _entry_backfill_dispatch_chunk(job)


def _is_stalled(job, stale_before):
    '''
    A batch is stalled when nothing has happened since stale_before: no
    dispatch and no sub-task completion. A slow batch that's still finishing
    monitors is left alone.
    '''
    activity = [t for t in (job.phase_started_at, job.last_progress_at) if t is not None]
    return bool(activity) and max(activity) < stale_before


def _fail_job(job, job_label, management_command):
    '''
    Out of retries: stop the job. chunk_start is cleared so that resuming it
    (flipping state back to RUNNING in the admin) re-dispatches the unfinished
    chunk instead of treating it as complete. The email goes out only once
    the FAILED state has committed, so a mail error can't roll it back.
    '''
    job.pending_tasks = 0
    job.chunk_start = None
    job.state = job.State.FAILED
    job.save()
    transaction.on_commit(lambda: _notify_job_failed(job, job_label, management_command))


def _notify_job_failed(job, job_label, management_command):
    '''
    A job that's exhausted its consecutive-failure budget stops retrying on
    its own -- email the site admins (settings.ADMINS) so it doesn't sit
    silently failed until someone happens to check `status`.
    '''
    mail_admins(
        subject=f'{job_label} failed',
        message=(
            f'{job_label} has failed after {job.consecutive_failures} consecutive '
            f'stalled batches and stopped retrying.\n\n'
            f'State: {job.state}\n'
            f'Cursor: {job.cursor}\n'
            f'Range: {job.range_start} - {job.range_end}\n'
            f'Last error: {job.last_error}\n\n'
            f'This job will not resume on its own. Check `{management_command} status` '
            f'for details, investigate the cause, and either fix the underlying issue '
            f'and `{management_command} start --force` a new run, or leave it as-is if '
            f'no further action is needed.'
        ),
    )


def _entry_backfill_dispatch_chunk(job):
    chunk_start = chunk_start_for(job.cursor, job.range_start, job.chunk_days)
    monitor_ids = monitors_with_legacy_data_in(chunk_start, job.cursor)

    job.chunk_start = chunk_start
    if job.consecutive_failures >= ENTRY_BACKFILL_MAX_CONSECUTIVE_FAILURES:
        job.consecutive_failures = 0  # resumed after FAILED: fresh retry budget
    job.batch_id += 1
    job.pending_tasks = len(monitor_ids)
    job.phase_started_at = timezone.now()
    job.save()

    job_id = job.pk
    batch_id = job.batch_id
    chunk_end = job.cursor
    for monitor_id in monitor_ids:
        transaction.on_commit(
            lambda m=monitor_id: backfill_monitor_chunk(job_id, str(m), chunk_start, chunk_end, batch_id)
        )


def _entry_backfill_complete_chunk(job):
    job.cursor = job.chunk_start
    job.chunk_start = None
    job.pending_tasks = 0
    job.consecutive_failures = 0
    job.last_error = ''
    if job.cursor <= job.range_start:
        job.state = EntryBackfillJob.State.DONE
    job.save()


def _entry_backfill_restart_batch(job):
    job.consecutive_failures += 1
    job.last_error = (
        f'Batch {job.batch_id} stalled with {job.pending_tasks} pending task(s); restarting.'
    )

    if job.consecutive_failures >= ENTRY_BACKFILL_MAX_CONSECUTIVE_FAILURES:
        _fail_job(job, 'Legacy entries backfill', 'backfill_legacy_entries')
        return

    chunk_start = job.chunk_start
    monitor_ids = monitors_with_legacy_data_in(chunk_start, job.cursor)

    job.batch_id += 1
    job.pending_tasks = len(monitor_ids)
    job.phase_started_at = timezone.now()
    job.save()

    job_id = job.pk
    batch_id = job.batch_id
    chunk_end = job.cursor
    for monitor_id in monitor_ids:
        transaction.on_commit(
            lambda m=monitor_id: backfill_monitor_chunk(job_id, str(m), chunk_start, chunk_end, batch_id)
        )


PIPELINE_BACKFILL_LOCK_STALE_SECONDS = 30
PIPELINE_BACKFILL_BATCH_STALE_MINUTES = 60
PIPELINE_BACKFILL_MAX_CONSECUTIVE_FAILURES = 5


@db_periodic_task(crontab(minute='*'), priority=1, queue='secondary')
def reprocess_legacy_pipeline_tick():
    '''
    Drive one step of the active PipelineBackfillJob, if any. Never blocks on
    the sub-tasks it dispatches. See
    docs/superpowers/specs/2026-07-28-legacy-entries-backfill-design.md.
    '''
    now = timezone.now()

    with transaction.atomic():
        job = (
            PipelineBackfillJob.objects
            .select_for_update(skip_locked=True)
            .filter(state=PipelineBackfillJob.State.RUNNING)
            .filter(
                Q(locked_at__isnull=True) |
                Q(locked_at__lt=now - timedelta(seconds=PIPELINE_BACKFILL_LOCK_STALE_SECONDS))
            )
            .order_by('created')
            .first()
        )
        if job is None:
            return

        job.locked_at = now
        job.save(update_fields=['locked_at'])

        if job.pending_tasks > 0:
            stale_before = now - timedelta(minutes=PIPELINE_BACKFILL_BATCH_STALE_MINUTES)
            if _is_stalled(job, stale_before):
                _pipeline_backfill_restart_batch(job)
            return

        if job.chunk_start is not None:
            _pipeline_backfill_complete_chunk(job)
        else:
            _pipeline_backfill_dispatch_chunk(job)


def _pipeline_backfill_dispatch_chunk(job):
    # Unlike the RAW backfill, reprocessing walks forward from range_start:
    # the cleaning step for each entry depends on the one before it.
    chunk_start = job.cursor
    chunk_end = chunk_end_for(chunk_start, job.range_end, job.chunk_days)
    monitor_ids = monitors_with_incomplete_pipelines_in(chunk_start, chunk_end, job.stop_before)

    job.chunk_start = chunk_start
    if job.consecutive_failures >= PIPELINE_BACKFILL_MAX_CONSECUTIVE_FAILURES:
        job.consecutive_failures = 0  # resumed after FAILED: fresh retry budget
    job.batch_id += 1
    job.pending_tasks = len(monitor_ids)
    job.phase_started_at = timezone.now()
    job.save()

    job_id = job.pk
    batch_id = job.batch_id
    stop_before = job.stop_before
    for monitor_id in monitor_ids:
        transaction.on_commit(
            lambda m=monitor_id: reprocess_monitor_chunk(job_id, str(m), chunk_start, chunk_end, batch_id, stop_before)
        )


def _pipeline_backfill_complete_chunk(job):
    job.cursor = chunk_end_for(job.chunk_start, job.range_end, job.chunk_days)
    job.chunk_start = None
    job.pending_tasks = 0
    job.consecutive_failures = 0
    job.last_error = ''
    if job.cursor >= job.range_end:
        job.state = PipelineBackfillJob.State.DONE
    job.save()


def _pipeline_backfill_restart_batch(job):
    job.consecutive_failures += 1
    job.last_error = (
        f'Batch {job.batch_id} stalled with {job.pending_tasks} pending task(s); restarting.'
    )

    if job.consecutive_failures >= PIPELINE_BACKFILL_MAX_CONSECUTIVE_FAILURES:
        _fail_job(job, 'Legacy pipeline reprocessing', 'reprocess_legacy_pipeline')
        return

    chunk_start = job.chunk_start
    chunk_end = chunk_end_for(chunk_start, job.range_end, job.chunk_days)
    monitor_ids = monitors_with_incomplete_pipelines_in(chunk_start, chunk_end, job.stop_before)

    job.batch_id += 1
    job.pending_tasks = len(monitor_ids)
    job.phase_started_at = timezone.now()
    job.save()

    job_id = job.pk
    batch_id = job.batch_id
    stop_before = job.stop_before
    for monitor_id in monitor_ids:
        transaction.on_commit(
            lambda m=monitor_id: reprocess_monitor_chunk(job_id, str(m), chunk_start, chunk_end, batch_id, stop_before)
        )
