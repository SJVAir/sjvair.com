import time

from datetime import timedelta
from pprint import pformat

from django.conf import settings
from django.db.models import F, OuterRef, Subquery
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from huey import crontab
from huey.contrib.djhuey import db_task, db_periodic_task, HUEY
from huey.exceptions import TaskLockedException

from camp.apps.monitors.models import Entry
from camp.apps.monitors.purpleair.api import purpleair_api
from camp.apps.monitors.purpleair.models import PurpleAir


@db_periodic_task(crontab(minute='*/2'), priority=50)
def update_realtime():
    print('[update_realtime]')
    if HUEY.pending_count() > settings.MAX_QUEUE_SIZE:
        return

    sensors = purpleair_api.list_group_members(settings.PURPLEAIR_GROUP_ID)
    for sensor in sensors:
        process_data.schedule([sensor], delay=1, priority=30)


@db_task()
def process_data(payload):
    try:
        monitor = PurpleAir.objects.get(purple_id=payload['sensor_index'])
    except PurpleAir.DoesNotExist:
        monitor = PurpleAir(purple_id=payload['sensor_index'])
        monitor.update_data()
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
            monitor = PurpleAir(
                purple_id=sensor['sensor_index']
            )

        monitor.update_data(sensor)
        monitor.save()
