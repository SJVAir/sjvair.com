from datetime import timedelta

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from django_huey import db_task, db_periodic_task
from huey import crontab

from camp.apps.monitors.aqlite.models import AQLite
from camp.utils.datetime import make_aware


@db_periodic_task(crontab(minute='*/5'), priority=50)
def update_realtime():
    start = timezone.now()
    print(f'\n=== AQLite Import Start: {start.time()}\n')

    monitors = (AQLite.objects
        .select_related('organization')
        .filter(organization__isnull=False, organization__is_enabled=True)
        .get_active()
    )

    for monitor in monitors:
        process_data.schedule([monitor.pk], delay=1, priority=40)

    end = timezone.now()
    print(f'\n=== AQLite Import Done: {start.time()} - {end.time()} ({end - start})\n')


@db_task()
def process_data(monitor_id):
    from camp.apps.calibrations import processors

    monitor = AQLite.objects.select_related('organization').get(pk=monitor_id)

    end = timezone.now()
    start = end - timedelta(minutes=10)
    current_hour = end.replace(minute=0, second=0, microsecond=0)

    payloads = monitor.organization.api.get_time_series(
        device_id=monitor.device_id,
        start=start,
        end=end,
        average=0,
    )

    affected_hours = set()
    for payload in payloads:
        entries = monitor.create_entries(payload)
        for entry in entries:
            monitor.process_entry_pipeline(entry)
        ts = make_aware(parse_datetime(payload['timestamp']))
        affected_hours.add(ts.replace(minute=0, second=0, microsecond=0))

    # Aggregate any complete affected hours. Handles backfilled entries whose
    # historical hours won't be revisited by the scheduled aggregate_hourly task.
    for hour_start in sorted(affected_hours):
        hour_end = hour_start + timedelta(hours=1)
        if hour_end <= current_hour:
            processors.AQLiteHourlyAggregator.aggregate(monitor, hour_start, hour_end)

    monitor.save()


@db_periodic_task(crontab(minute='5'), priority=50)
def aggregate_hourly():
    """Runs at :05 past each hour to aggregate the previous complete hour."""
    now = timezone.now()
    hour_end = now.replace(minute=0, second=0, microsecond=0)
    hour_start = hour_end - timedelta(hours=1)

    monitors = (AQLite.objects
        .select_related('organization')
        .filter(organization__isnull=False, organization__is_enabled=True)
    )

    for monitor in monitors:
        aggregate_monitor_hour.schedule([monitor.pk, hour_start, hour_end], delay=1, priority=40)


@db_task()
def aggregate_monitor_hour(monitor_id, hour_start, hour_end):
    from camp.apps.calibrations import processors
    monitor = AQLite.objects.get(pk=monitor_id)
    processors.AQLiteHourlyAggregator.aggregate(monitor, hour_start, hour_end)
    monitor.save()
