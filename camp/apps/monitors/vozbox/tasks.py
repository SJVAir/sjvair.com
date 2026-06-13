from datetime import timedelta

from django.utils import timezone

from django_huey import db_task, db_periodic_task
from huey import crontab

from camp.apps.entries import models as entry_models
from camp.apps.monitors.vozbox.api import VozBoxClient
from camp.apps.monitors.vozbox.models import VOZBox


@db_periodic_task(crontab(minute='*/10'), priority=50)
def import_realtime():
    start = timezone.now()
    print(f'\n=== VOZbox Import Start: {start.time()}\n')

    today = timezone.localdate()
    yesterday = today - timedelta(days=1)

    combined = {}
    with VozBoxClient() as client:
        for d in [yesterday, today]:
            data = client.get_daily_data(d)
            if data is None:
                continue
            for coreid, rows in data.items():
                combined.setdefault(coreid, []).extend(rows)

    for coreid, rows in combined.items():
        process_device.schedule([coreid, rows], delay=1, priority=40)

    end = timezone.now()
    print(f'\n=== VOZbox Import Done: {start.time()} - {end.time()} ({end - start})\n')


@db_task()
def process_device(coreid, rows):
    try:
        monitor = VOZBox.objects.get(sensor_id=coreid)
    except VOZBox.DoesNotExist:
        monitor = VOZBox(sensor_id=coreid)
        if rows:
            latest_row = max(rows, key=lambda r: r['timestamp'])
            monitor.update_data(latest_row)
        monitor.save()

    if not rows:
        return

    # Cutoff: skip rows already in DB. validation_check() is the safety net.
    latest_ts = (entry_models.PM25.objects
        .filter(monitor=monitor, sensor='a', stage=entry_models.PM25.Stage.RAW)
        .order_by('-timestamp')
        .values_list('timestamp', flat=True)
        .first()
    )

    for row in sorted(rows, key=lambda r: r['timestamp']):
        if latest_ts and row['timestamp'] <= latest_ts:
            continue
        entries = monitor.create_entries(row)
        for entry in entries:
            monitor.process_entry_pipeline(entry)

    latest_row = max(rows, key=lambda r: r['timestamp'])
    monitor.update_data(latest_row)
    monitor.save()
