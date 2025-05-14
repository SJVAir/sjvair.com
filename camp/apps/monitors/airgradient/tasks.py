import time

from django.conf import settings

from django_huey import db_task, db_periodic_task
from huey import crontab

from camp.apps.monitors.airgradient.models import AirGradient, Place
from camp.utils.datetime import parse_timestamp


@db_periodic_task(crontab(minute='*'), priority=50)
def update_realtime():
    for place in Place.objects.filter(is_enabled=True):
        try:
            data = place.api.get_all_channel_measures()
        except Exception as e:
            # Log and skip if a token is bad or unavailable
            print(f'[AirGradient] Error fetching data for {place.name}: {e}')
            continue

        for payload in data:
            process_data.schedule([payload, place.pk], delay=1, priority=40)


@db_task()
def process_data(payload, place_id):
    try:
        monitor = AirGradient.objects.get(location_id=payload['locationId'])
    except AirGradient.DoesNotExist:
        monitor = AirGradient(
            location_id=payload['locationId'],
            place_id=place_id
        )
        monitor.update_data(payload)
        monitor.save()

    entries = monitor.create_entries(payload)
    for entry in entries:
        monitor.process_entry_pipeline(entry)

    monitor.save()

