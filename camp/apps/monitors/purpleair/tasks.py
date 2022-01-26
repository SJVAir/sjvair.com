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
from camp.apps.monitors.purpleair import api
from camp.apps.monitors.purpleair.models import PurpleAir


@db_periodic_task(crontab(minute='*/2'), priority=50)
def import_recent_data():
    print('[import_recent_data]')
    if HUEY.pending_count() > settings.MAX_QUEUE_SIZE:
        return

    for monitor in PurpleAir.objects.all():
        print('[import_recent_data]', monitor.name, '\n')
        import_monitor_data.schedule([monitor.pk], delay=1, priority=30)


@db_periodic_task(crontab(hour='23', minute='0'))
def update_monitor_data():
    for monitor in PurpleAir.objects.all():
        monitor.update_data()

@db_task()
def import_monitor_history(monitor_id, end=None):
    monitor = PurpleAir.objects.get(pk=monitor_id)
    end = end or timezone.now()
    feeds = monitor.get_feeds(end=end, results=1000)
    entry_count = 0

    print(f'[history] {monitor.name} ({monitor.pk}) | {end}')
    for sensor, feed in feeds.items():
        for payload in feed:
            entry_count += 1
            add_monitor_entry.schedule([monitor.pk, payload, sensor], delay=1, priority=10)
            timestamp = min([item['created_at'] for item in payload])
            if timestamp < end:
                end = timestamp

    if entry_count > 0:
        import_monitor_history(monitor_id, end)


@db_task()
def import_monitor_data(monitor_id, options=None):
    monitor = PurpleAir.objects.get(pk=monitor_id)
    print(f'[import_monitor_data] {monitor.name} ({monitor.pk})')
    monitor.save()

    if options is None:
        try:
            options = {'start': (monitor.entries
                .values_list('timestamp', flat=True)
                .latest('timestamp')
            )}
        except Entry.DoesNotExist:
            options = {'results': 100}

    feeds = monitor.get_feeds(**options)
    for sensor, feed in feeds.items():
        for payload in feed:
            add_monitor_entry.schedule([monitor.pk, payload, sensor], delay=1, priority=30)


@db_task()
def add_monitor_entry(monitor_id, payload, sensor=None):
    # CONSIDER: If we're skipping existing entries, we
    # probably don't need this lock
    key = '_'.join([
        'purpleair.entry',
        str(monitor_id),
        sensor if sensor is not None else '',
        str(payload[0]["created_at"]),
    ])

    try:
        with HUEY.lock_task(key):
            monitor = PurpleAir.objects.get(pk=monitor_id)
            entry = monitor.create_entry(payload, sensor=sensor)

            # If the entry was pulled from the database and is not
            # a new instance, we can end early since we already have it.
            if not entry._state.adding:
                return

            print(f'[add_monitor_entry] {monitor.name} ({monitor.pk})')
            entry = monitor.process_entry(entry)
            entry.save()
            monitor.check_latest(Entry.objects.get(pk=entry.pk))
    except TaskLockedException:
        print(f'[LOCKED:add_monitor_entry] {monitor_id} ({payload[0]["created_at"]})')
