import time

from datetime import timedelta

import requests

from django.conf import settings
from django.utils import timezone

from django_huey import db_task, db_periodic_task
from huey import crontab

from camp.apps.monitors.airgradient.models import AirGradient, Place
from camp.utils.datetime import parse_timestamp


@db_periodic_task(crontab(minute='*'), priority=50)
def update_realtime():
    start = timezone.now()
    print(f'\n=== AirGradient Import Start: {start.time()}\n')

    for place in Place.objects.filter(is_enabled=True):
        seen_ids = set()
        try:
            data = place.api.get_all_channel_measures()
        except Exception as e:
            # Log and skip if a token is bad or unavailable
            print(f'[AirGradient] Error fetching data for {place.name}: {e}')
            continue

        for payload in data:
            seen_ids.add(payload['locationId'])
            # process_data.call_local(payload, place.pk)
            process_data.schedule([payload, place.pk], delay=1, priority=40)

        # Any monitors that are active but missing
        # from the group should be manually retried.
        missing_monitors = (AirGradient.objects
            .filter(place_id=place.pk)
            .exclude(sensor_id__in=seen_ids)
            .select_related('place')
            .get_active()
        )

        for monitor in missing_monitors:
            monitor.import_latest()

    end = timezone.now()
    print(f'\n=== AirGradient Import Done: {start.time()} - {end.time()} ({end - start})\n')


@db_task()
def process_data(payload, place_id):
    try:
        monitor = AirGradient.objects.get(sensor_id=payload['locationId'])
    except AirGradient.DoesNotExist:
        monitor = AirGradient(
            sensor_id=payload['locationId'],
            place_id=place_id
        )
        monitor.update_data(payload)
        monitor.save()

    entries = monitor.create_entries(payload)
    for entry in entries:
        monitor.process_entry_pipeline(entry)

    monitor.save()


# This is the implementation logic af a historical AirGradient import. However
# AirGradient does not currently have an API endpoint to get the raw data
# broken into channels, only by an average of the two channels. If and when
# they implement such an endpoint, we can uncomment this and import historical
# data from AirGradient. --DMP

@db_task(queue='secondary')
def import_airgradient_history(monitor_id, start_date=None, end_date=None):
    monitor = AirGradient.objects.select_related('place').get(pk=monitor_id)

    start = start_date or monitor.first_seen
    end = end_date or timezone.now()

    current = start
    ts = []
    while current < end:
        batch_end = min(current + timedelta(days=1), end)

        try:
            results = monitor.place.api.get_raw_measures(
                location_id=monitor.sensor_id,
                from_time=current.isoformat(),
                to_time=batch_end.isoformat(),
            )
        except requests.HTTPError as err:
            if err.response.status_code == 404:
                # 404 means there was no data, so try the next date range.
                current = batch_end + timedelta(seconds=1)
                print(f'404: {monitor.name} ({current} - {batch_end})')
                continue
            # We got an HTTPError that wasn't a 404, which means something
            # else bad has happened. Duck out early.
            break

        # Ensure oldest-first order
        results = sorted(results, key=lambda r: r.get('timestamp'))

        print(f'{monitor.name} ({current} - {batch_end}): {len(results)}')

        max_timestamp = None
        for i, result in enumerate(results):
            result['timestamp'] = parse_timestamp(result['timestamp'])
            if result['timestamp'] in ts:
                print(f'DUPLICATE #{i}:', result['timestamp'])
            else:
                ts.append(result['timestamp'])
            if not max_timestamp or result['timestamp'] > max_timestamp:
                max_timestamp = result['timestamp']
            # entries = monitor.create_entries(result)
            # for entry in entries:
            #     monitor.process_entry_pipeline(entry)
            #     if not max_timestamp or entry.timestamp > max_timestamp:
            #         max_timestamp = entry.timestamp

        # monitor.save()

        # If no data was returned, break to avoid infinite loops
        if not max_timestamp:
            break

        current = max_timestamp + timedelta(seconds=1)
        time.sleep(1)  # Be gentle to their servers

