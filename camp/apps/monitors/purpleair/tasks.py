import time

from datetime import timedelta

from django.conf import settings
from django.db.models import F, OuterRef, Subquery
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from django_huey import db_task, db_periodic_task
from huey import crontab

from camp.apps.monitors.models import Entry
from camp.apps.monitors.purpleair.api import purpleair_api, chunk_date_range
from camp.apps.monitors.purpleair.models import PurpleAir
from camp.utils.datetime import parse_timestamp


@db_periodic_task(crontab(minute='*/2'), priority=50)
def update_realtime():
    sensors = purpleair_api.list_group_members(settings.PURPLEAIR_GROUP_ID)
    for sensor in sensors:
        process_data.schedule([sensor], delay=1, priority=40)


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
def upsert_monitor_history(monitor_id, start_date=None, end_date=None):
    monitor = PurpleAir.objects.get(pk=monitor_id)
    entries = purpleair_api.get_sensor_history(monitor.purple_id, start_date, end_date)

    for entry in entries:
        for sensor in PurpleAir.SENSORS:
            try:
                instance = Entry.objects.get(
                    monitor_id=monitor.pk,
                    timestamp=parse_timestamp(entry['time_stamp']),
                    sensor=sensor,
                )
                if instance.pm25_reported != entry[f'pm2.5_atm_{sensor}']:
                    instance.pm25_reported = entry[f'pm2.5_atm_{sensor}']
                    instance.save()
            except Entry.DoesNotExist:
                monitor.create_entries(entry)


@db_task(queue='secondary')
def upsert_monitor_history_batched(monitor_id, start_date=None, end_date=None):
    chunks = chunk_date_range(start_date, end_date)
    for start_date, end_date in chunks:
        import_monitor_history(monitor_id, start_date, end_date)
        time.sleep(1)


@db_task(queue='secondary')
def import_monitor_history(monitor_id, start_date=None, end_date=None):
    monitor = PurpleAir.objects.get(pk=monitor_id)
    entries = purpleair_api.get_sensor_history(monitor.purple_id, start_date, end_date)

    for entry in entries:
        monitor.create_entries(entry)


@db_task(queue='secondary')
def import_monitor_history_batched(monitor_id, start_date=None, end_date=None):
    chunks = chunk_date_range(start_date, end_date)
    for start_date, end_date in chunks:
        import_monitor_history(monitor_id, start_date, end_date)
        time.sleep(1)