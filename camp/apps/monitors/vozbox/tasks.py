import logging
from datetime import timedelta

from django.utils import timezone

from django_huey import db_task, db_periodic_task
from huey import crontab

from camp.apps.entries import models as entry_models
from camp.apps.monitors.vozbox.api import VozBoxClient
from camp.apps.monitors.vozbox.models import VOZBox

logger = logging.getLogger(__name__)


def _bin_rows(rows, interval_minutes=10):
    """One row per N-minute bucket; keeps the earliest row in each bucket."""
    buckets = {}
    for row in sorted(rows, key=lambda r: r['timestamp']):
        ts = row['timestamp']
        floored = ts.replace(second=0, microsecond=0)
        key = floored.replace(minute=(floored.minute // interval_minutes) * interval_minutes)
        if key not in buckets:
            buckets[key] = row
    return list(buckets.values())


@db_periodic_task(crontab(minute='*/10'), priority=50)
def import_realtime():
    start = timezone.now()
    logger.info('VOZbox import start')

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
        process_device.schedule([coreid, _bin_rows(rows)], delay=1, priority=40)

    logger.info('VOZbox import done in %s', timezone.now() - start)


@db_task()
def process_device(coreid, rows):
    monitor, created = VOZBox.objects.get_or_create(sensor_id=coreid)
    if created and rows:
        monitor.update_data(max(rows, key=lambda r: r['timestamp']))
        monitor.save()

    if not rows:
        return

    rows = _bin_rows(rows)

    # Cutoff: skip rows already in DB. validation_check() is the safety net.
    latest_ts = (entry_models.PM25.objects
        .filter(monitor=monitor, sensor='a', stage=entry_models.PM25.Stage.RAW)
        .order_by('-timestamp')
        .values_list('timestamp', flat=True)
        .first()
    )

    for row in rows:
        if latest_ts and row['timestamp'] <= latest_ts:
            continue
        entries = monitor.create_entries(row)
        for entry in entries:
            monitor.process_entry_pipeline(entry)

    latest_row = max(rows, key=lambda r: r['timestamp'])
    monitor.update_data(latest_row)
    monitor.save()
