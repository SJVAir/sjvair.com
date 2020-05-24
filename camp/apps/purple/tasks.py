import time

from datetime import timedelta
from pprint import pformat

from django.db.models import F, OuterRef, Subquery
from django.utils import timezone

from huey import crontab
from huey.contrib.djhuey import db_task, db_periodic_task

from camp.apps.purple import api
from camp.apps.purple.models import PurpleAir, Entry


@db_periodic_task(crontab(minute='*'))
def update_latest_entries():
    print('[update_latest_entries]')
    PurpleAir.objects.annotate(
        latest_entry=Subquery(
            Entry.objects.filter(device=OuterRef('pk')).order_by('-timestamp').values('pk')[:1]
        )
    ).update(latest_id=F('latest_entry'))


@db_periodic_task(crontab(minute='*/2'))
def import_recent_data():
    print('[import_recent_data]')
    for device in PurpleAir.objects.all():
        import_device_data(device.pk)


@db_task()
def import_device_history(device_id, end=None):
    device = PurpleAir.objects.get(pk=device_id)

    def get_feed(end):
        return list(device.feed(end=end, results=8000))

    end = end or timezone.now()
    feed = get_feed(end)
    while len(feed):
        print(f'[history] {device.label} ({device.pk}) | {end} | {len(feed)}')
        for items in feed:
            add_device_entry(device.pk, items)
        end = min([items[0]['created_at'] for items in feed]) - timedelta(seconds=1)
        feed = get_feed(end)
        # feed = get_feed(feed[0][0]['created_at'] - timedelta(seconds=1))


@db_task()
def import_device_data(device_id, options=None):
    device = PurpleAir.objects.get(pk=device_id)
    print(f'[import_device_data:start] {device.label} ({device.pk})')
    device.update_device_data()
    device.save()

    if options is None:
        try:
            options = {'start': device.entries.latest('timestamp').timestamp}
        except Entry.DoesNotExist:
            options = {'results': 1}

    feed = device.feed(**options)
    for index, items in enumerate(feed):
        add_device_entry(device.pk, items)

    print(f'[import_device_data:end] {device.label} ({device.pk}) - {index + 1}')


@db_task()
def add_device_entry(device_id, items):
    device = PurpleAir.objects.get(pk=device_id)
    print(f'[add_device_entry] {device.label} ({device.pk})')
    device.add_entry(items)
