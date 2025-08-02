import time

from django.conf import settings
from django.utils import timezone

from django_huey import db_task, db_periodic_task
from huey import crontab

from camp.apps.monitors.purpleair.api import purpleair_api
from camp.apps.monitors.purpleair.models import PurpleAir
from camp.utils.datetime import chunk_date_range


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
        .exclude(purple_id__in=seen_ids)
        .get_active()
    )

    for monitor in missing_monitors:
        monitor.import_latest()

    end = timezone.now()
    print(f'\n=== PurpleAir Import Done: {start.time()} - {end.time()} ({end - start})\n')


@db_task()
def process_data(payload):
    try:
        monitor = PurpleAir.objects.get(purple_id=payload['sensor_index'])
    except PurpleAir.DoesNotExist:
        data = purpleair_api.get_sensor(payload['sensor_index'])
        if data is None:
            purpleair_api.delete_group_member(settings.PURPLEAIR_GROUP_ID, payload['sensor_index'])
            return

        monitor = PurpleAir(purple_id=payload['sensor_index'])
        monitor.update_data(data)
        monitor.save()

    entries = monitor.create_entries(payload)
    for entry in entries:
        monitor.process_entry_pipeline(entry)

    # Legacy
    entries = monitor.create_entries_legacy(payload)
    for entry in entries:
        monitor.check_latest(entry)

    monitor.save()


@db_periodic_task(crontab(hour='23', minute='0'))
def update_monitor_data():
    sensors = purpleair_api.list_group_members(settings.PURPLEAIR_GROUP_ID)
    for sensor in sensors:
        try:
            monitor = PurpleAir.objects.get(purple_id=sensor['sensor_index'])
        except PurpleAir.DoesNotExist:
            monitor = PurpleAir(purple_id=sensor['sensor_index'])

        data = purpleair_api.get_sensor(monitor.purple_id)
        if data is None:
            purpleair_api.delete_group_member(settings.PURPLEAIR_GROUP_ID, monitor.purple_id)
            continue

        monitor.update_data(data)
        monitor.save()


@db_task(queue='secondary')
def import_monitor_history(monitor_id, start_date=None, end_date=None):
    monitor = PurpleAir.objects.get(pk=monitor_id)
    entries = purpleair_api.get_sensor_history(monitor.purple_id, start_date, end_date)

    for entry in entries:
        process_data.call_local(entry)


@db_task(queue='secondary')
def import_monitor_history_batched(monitor_id, start_date=None, end_date=None):
    chunks = chunk_date_range(start_date, end_date)
    for start_date, end_date in chunks:
        import_monitor_history(monitor_id, start_date, end_date)
        time.sleep(1)
