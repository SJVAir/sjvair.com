from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import F, Q
from django.template.loader import render_to_string
from django.utils import timezone

from django_huey import db_task, db_periodic_task
from huey import crontab

from camp.utils.text import render_markdown
from camp.apps.monitors.legacy_backfill import (
    LEGACY_BACKFILL_MAP, chunk_start_for, find_missing_raw_entries,
    monitors_with_legacy_data_in,
)
from .models import Entry, EntryBackfillJob, Monitor


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
    '''
    monitor = _resolve_monitor_subclass(monitor_id)

    created_count = 0
    for entry_model, mapping in LEGACY_BACKFILL_MAP.get(type(monitor), {}).items():
        missing = find_missing_raw_entries(monitor, entry_model, mapping, chunk_start, chunk_end)
        if missing:
            entry_model.objects.bulk_create(
                missing,
                update_conflicts=True,
                unique_fields=['monitor', 'timestamp', 'sensor', 'stage', 'processor'],
                update_fields=[f.name for f in entry_model.declared_fields],
            )
            created_count += len(missing)

    EntryBackfillJob.objects.filter(
        pk=job_id, batch_id=batch_id,
    ).update(
        pending_tasks=F('pending_tasks') - 1,
        raw_entries_created=F('raw_entries_created') + created_count,
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


@db_periodic_task(crontab(minute='*'), priority=1, queue='primary')
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
            if job.phase_started_at and job.phase_started_at < stale_before:
                _entry_backfill_restart_batch(job)
            return

        if job.chunk_start is not None:
            _entry_backfill_complete_chunk(job)
        else:
            _entry_backfill_dispatch_chunk(job)


def _entry_backfill_dispatch_chunk(job):
    chunk_start = chunk_start_for(job.cursor, job.range_start, job.chunk_days)
    monitor_ids = monitors_with_legacy_data_in(chunk_start, job.cursor)

    job.chunk_start = chunk_start
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
        job.pending_tasks = 0
        job.state = EntryBackfillJob.State.FAILED
        job.save()
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
