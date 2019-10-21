from datetime import timedelta
from pprint import pformat

from django.utils import timezone

from huey import crontab
from huey.contrib.djhuey import db_task, db_periodic_task

from camp.apps.purple import api
from camp.apps.purple.models import PurpleAir, Entry

pm2_keymap = (
    ('pm25_standard', 'PM2.5 (CF=1)'),
    ('pm10_env', 'PM1.0 (ATM)'),
    ('pm25_env', 'PM2.5 (ATM)'),
    ('pm100_env', 'PM10.0 (ATM)'),
)


@db_task()
def import_purple_device(device_id, options=None, retry=False):
    options = options or {}
    device = PurpleAir.objects.get(pk=device_id)
    print(f'Importing: {device.label} ({device.pk})')

    for items in device.feed(**options):
        # Return early if we don't have entries on
        # both ThingSpeak devices. By the time this
        # runs again, it should have the data we're
        # missing.
        if len(items) == 1:
            print(f'Missing data: {device.label} ({device.pk})')
            return

        try:
            entry = Entry.objects.get(
                device=device,
                data__0__entry_id=items[0]['entry_id']
            )
        except Entry.DoesNotExist:
            entry = Entry(device=device)

        entry.timestamp = items[0]['created_at']
        entry.position = device.position
        entry.location = device.location

        entry.data = items
        entry.fahrenheit = items[0].get('Temperature')
        entry.humidity = items[0].get('Humidity')
        entry.pressure = items[1].get('Pressure')

        entry.pm2_a = {ck: items[0].get(pk) for ck, pk in pm2_keymap}
        entry.pm2_b = {ck: items[1].get(pk) for ck, pk in pm2_keymap}
        entry.save()

    device.latest = Entry.objects.latest('timestamp')
    device.save()


@db_periodic_task(crontab(minute='*/5'))
def import_purple_data():
    options = {'end': timezone.now()}
    options['start'] = options['end'] - timedelta(minutes=6)
    purple_list = PurpleAir.objects.values_list('pk', flat=True)
    for device_id in purple_list:
        import_purple_device(device_id, options)
