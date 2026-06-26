from datetime import timedelta

import requests

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from django_huey import db_task, db_periodic_task
from huey import crontab

from camp.apps.entries.models import O3
from camp.apps.monitors.aqlite.models import AQLite
from camp.utils.datetime import make_aware


@db_periodic_task(crontab(minute='*/5'), priority=50)
def update_realtime():
    start = timezone.now()
    print(f'\n=== AQLite Import Start: {start.time()}\n')

    monitors = AQLite.objects.filter(organization__isnull=False, organization__is_enabled=True)

    for monitor in monitors:
        process_data.schedule([monitor.pk], delay=1, priority=40)

    end = timezone.now()
    print(f'\n=== AQLite Import Done: {start.time()} - {end.time()} ({end - start})\n')


@db_task()
def process_data(monitor_id):
    from camp.apps.calibrations import processors

    monitor = AQLite.objects.select_related('organization').get(pk=monitor_id)

    now = timezone.now()
    current_hour = now.replace(minute=0, second=0, microsecond=0)

    # Fetch from the last known RAW entry so we never miss a gap (backfill,
    # downtime, task delay). Capped at 24h so historical imports don't cause
    # an unbounded API request on the next realtime fetch.
    latest_raw = (
        O3.objects
        .filter(monitor=monitor, stage=O3.Stage.RAW)
        .order_by('-timestamp')
        .values_list('timestamp', flat=True)
        .first()
    )
    start = max(latest_raw, now - timedelta(hours=24)) if latest_raw else None

    payloads = monitor.organization.api.get_time_series(
        device_id=monitor.device_id,
        start=start,
        average=0,
    )

    affected_hours = set()
    try:
        for payload in payloads:
            entries = monitor.create_entries(payload)
            for entry in entries:
                monitor.process_entry_pipeline(entry)
            ts = make_aware(parse_datetime(payload['timestamp']))
            affected_hours.add(ts.replace(minute=0, second=0, microsecond=0))
    except requests.exceptions.RequestException as e:
        print(f'[AQLite] API error for {monitor.device_id}: {e}')

    if affected_hours:
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
    if processors.AQLiteHourlyAggregator.aggregate(monitor, hour_start, hour_end):
        monitor.save()


# Anything longer than this between consecutive RAW entries is treated as a gap.
_GAP_THRESHOLD = timedelta(minutes=10)
_ONE_SECOND = timedelta(seconds=1)


@db_periodic_task(crontab(minute='30'), priority=50)
def fill_gaps():
    """Hourly: detect RAW O3 gaps in the last 24h and refetch from the API."""
    monitors = AQLite.objects.filter(organization__isnull=False, organization__is_enabled=True)
    for monitor in monitors:
        fill_monitor_gaps.schedule([monitor.pk], delay=1, priority=40)


@db_task()
def fill_monitor_gaps(monitor_id):
    from camp.apps.calibrations import processors

    monitor = AQLite.objects.select_related('organization').get(pk=monitor_id)

    now = timezone.now()
    current_hour = now.replace(minute=0, second=0, microsecond=0)
    window_start = current_hour - timedelta(hours=24)

    raw_timestamps = list(
        O3.objects
        .filter(monitor=monitor, stage=O3.Stage.RAW,
                timestamp__gte=window_start, timestamp__lte=now)
        .order_by('timestamp')
        .values_list('timestamp', flat=True)
    )

    # Any interval > _GAP_THRESHOLD between consecutive timestamps is a gap.
    # Includes the leading edge (window_start → first entry) and trailing edge
    # (last entry → now) so offline periods at either end are also caught.
    checkpoints = [window_start] + raw_timestamps + [now]
    gaps = [
        (checkpoints[i - 1] + _ONE_SECOND, checkpoints[i] - _ONE_SECOND)
        for i in range(1, len(checkpoints))
        if checkpoints[i] - checkpoints[i - 1] > _GAP_THRESHOLD
    ]

    if not gaps:
        return

    affected_hours = set()
    for gap_start, gap_end in gaps:
        try:
            for payload in monitor.organization.api.get_time_series(
                device_id=monitor.device_id,
                start=gap_start,
                end=gap_end,
                average=0,
            ):
                entries = monitor.create_entries(payload)
                for entry in entries:
                    monitor.process_entry_pipeline(entry)
                ts = make_aware(parse_datetime(payload['timestamp']))
                affected_hours.add(ts.replace(minute=0, second=0, microsecond=0))
        except requests.exceptions.RequestException as e:
            print(f'[AQLite] API error for {monitor.device_id} gap {gap_start}–{gap_end}: {e}')

    if not affected_hours:
        return

    for hour_start in sorted(affected_hours):
        hour_end = hour_start + timedelta(hours=1)
        if hour_end <= current_hour:
            processors.AQLiteHourlyAggregator.aggregate(monitor, hour_start, hour_end)

    monitor.save()
