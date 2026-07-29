from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.db.models import F
from django.template.loader import render_to_string
from django.utils import timezone

from django_huey import db_task, db_periodic_task
from huey import crontab

from camp.utils.text import render_markdown
from camp.apps.monitors.legacy_backfill import (
    LEGACY_BACKFILL_MAP, find_missing_raw_entries,
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
