import time

from datetime import timedelta
from pprint import pformat

from django.utils import timezone

from huey import crontab
from huey.contrib.djhuey import db_task, db_periodic_task

from camp.apps.purple import api
from camp.apps.purple.models import PurpleAir, Entry


@db_task()
def import_purple_data(device_id, options=None):
    options = options or {}
    device = PurpleAir.objects.get(pk=device_id)
    feed = list(device.feed(**options))
    print(f'''
        PurpleAir Import: {device.label} ({device.pk})
        - {len(feed)} entries
    ''')


    for items in feed:
        device.add_entry(items)

    device.latest = device.entries.latest('timestamp')
    device.save()


@db_periodic_task(crontab(minute='*'))
def periodic_purple_import():
    for device in PurpleAir.objects.all():
        device.update_device_data()
        device.save()

        try:
            options = {'start': device.entries.latest('timestamp').timestamp}
        except Entry.DoesNotExist:
            options = {'results': 60}

        import_purple_data(device.pk, options)
