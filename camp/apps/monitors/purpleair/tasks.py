import time

from datetime import datetime

from django.conf import settings
from django.contrib.gis.geos import Point
from django.db import transaction
from django.utils import timezone

from django_huey import db_task, db_periodic_task
from huey import crontab

from camp.apps.entries import models as entry_models
from camp.apps.monitors.purpleair.api import purpleair_api
from camp.apps.monitors.purpleair.models import PurpleAir
from camp.apps.regions.models import Region
from camp.utils import gis


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


@db_periodic_task(crontab(hour='23', minute='30'))
def find_new_monitors():
    members = {
        member['sensor_index'] for member in
        purpleair_api.get_group(settings.PURPLEAIR_GROUP_ID)['members']
    }

    counties = Region.objects.counties().combined_geometry()
    nwlng, selat, selng, nwlat = counties.extent

    monitors = purpleair_api.list_sensors(
        fields=['sensor_index', 'name', 'longitude', 'latitude'],
        nwlng=nwlng,
        selat=selat,
        selng=selng,
        nwlat=nwlat,
    )

    print('Total monitors from PurpleAir:', len(monitors))
    print('Number of monitors in our group:', len(members))

    for monitor in monitors:
        lat = monitor.get('latitude')
        lon = monitor.get('longitude')

        # Skip if there's no lat/lon.
        if lat is None or lon is None:
            continue

        # Skip if we already have it.
        if monitor['sensor_index'] in members:
            continue

        # Skip monitors outside the geographic boundaries.
        point = Point(lon, lat, srid=gis.EPSG_LATLON)
        if not counties.contains(point):
            continue

        # All we need to do is add it to the group within PurpleAir,
        # and we'll pick it up on the next import pass.
        print(f'Adding #{monitor["sensor_index"]} - {monitor["name"]}')
        purpleair_api.create_group_member(
            settings.PURPLEAIR_GROUP_ID,
            monitor['sensor_index']
        )


@db_task()
def process_data(payload, cutoff_stage=None):
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
        monitor.process_entry_pipeline(entry, cutoff_stage=cutoff_stage)

    # Legacy
    entries = monitor.create_entries_legacy(payload)
    for entry in entries:
        monitor.check_latest(entry)

    monitor.save()


@db_task(queue='secondary')
def import_monitor_history(monitor_id, start_date, end_date, chunk_size=28):
    monitor = PurpleAir.objects.get(pk=monitor_id)
    history = purpleair_api.get_sensor_history(
        sensor_index=monitor.purple_id,
        start_date=start_date,
        end_date=end_date,
        batch_days=28,
    )

    entries = {E: [] for E in entry_models.BaseEntry.get_subclasses()}

    for i, payload in enumerate(history):
        for entry in monitor.create_entries(payload, save=False):
            EntryModel = type(entry)
            entries[EntryModel].append(entry)
            if len(entries[EntryModel]) >= 5000:
                print(f'Saving {len(entries[EntryModel])} {EntryModel.entry_type} {entries[EntryModel][-1].timestamp}')
                EntryModel.objects.bulk_create(entries[EntryModel], ignore_conflicts=True)
                entries[EntryModel] = []

    for EntryModel in entries.keys():
        if entries[EntryModel]:
            print(f'Saving {len(entries[EntryModel])} {EntryModel.entry_type}...')
            EntryModel.objects.bulk_create(entries[EntryModel], ignore_conflicts=True)


@db_task(queue='secondary')
def process_monitor_history(monitor_id, start_date, end_date):
    monitor = PurpleAir.objects.get(pk=monitor_id)

    for EntryModel in entry_models.BaseEntry.get_subclasses():
        if not monitor.is_processable(EntryModel):
            continue

        queryset = (EntryModel.objects
            .filter(
                monitor_id=monitor.pk,
                timestamp__range=(start_date, end_date),
                stage=EntryModel.Stage.RAW,
                derived_entries__isnull=True
            )
            .order_by('timestamp')
            .iterator(chunk_size=1000)
        )

        for i, entry in enumerate(queryset):
            if (i % 5000) == 0:
                print(i, entry.entry_type, entry.timestamp)
            monitor.process_entry_pipeline(entry)




