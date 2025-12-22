import os

from datetime import datetime, timedelta

from django.core.files.storage import default_storage, FileSystemStorage
from django.utils import timezone

from django_huey import db_task

from camp.apps.entries import models as entry_models
from camp.apps.entries.utils import generate_export_path
from camp.apps.monitors.models import Monitor
from camp.utils.datetime import chunk_date_range
from camp.utils.email import send_email


def migrate_legacy_entry(monitor, entry):
    entry_map = [
        (entry_models.PM25, {'pm25_reported': 'value'}),
        (entry_models.PM10, {'pm10': 'value'}),
        (entry_models.PM100, {'pm100': 'value'}),

        (entry_models.Particulates, {
            'particles_03um': 'particles_03um',
            'particles_05um': 'particles_05um',
            'particles_10um': 'particles_10um',
            'particles_25um': 'particles_25um',
            'particles_50um': 'particles_50um',
            'particles_100um': 'particles_100um',
        }),

        (entry_models.Temperature, {'fahrenheit': 'value'}),
        (entry_models.Humidity, {'humidity': 'value'}),
        (entry_models.Pressure, {'pressure': 'value'}),
        (entry_models.O3, {'ozone': 'value'}),
    ]

    new_entries = []

    for model, field_map in entry_map:
        if model not in monitor.ENTRY_CONFIG:
            continue

        data = {'timestamp': entry.timestamp}
        missing_data = False

        for old_field, new_field in field_map.items():
            value = getattr(entry, old_field, None)
            if value is None:
                missing_data = True
                break
            data[new_field] = value

        if missing_data:
            continue

        entry_config = monitor.ENTRY_CONFIG.get(model, {})
        sensor_config = entry_config.get('sensors')
        sensor_allowed = True

        if sensor_config:
            if entry.sensor in sensor_config:
                data['sensor'] = entry.sensor
            else:
                sensor_allowed = False
        else:
            pm25_sensors = monitor.ENTRY_CONFIG.get(entry_models.PM25, {}).get('sensors') or []
            if pm25_sensors and entry.sensor != pm25_sensors[0]:
                sensor_allowed = False

        if not sensor_allowed:
            continue

        if new := monitor.create_entry(model, **data):
            new_entries.append(new)

    for entry in new_entries:
        monitor.process_entry_pipeline(entry, entry_models.PM25.Stage.CALIBRATED)


@db_task(queue='secondary')
def copy_legacy_entries_range(monitor_id, start, end):
    monitor = Monitor.objects.get(pk=monitor_id)
    queryset = monitor.entries.filter(timestamp__range=(start, end))
    for entry in queryset.iterator():
        migrate_legacy_entry(monitor, entry)


@db_task(queue='secondary')
def copy_legacy_entries(monitor_id):
    monitor = Monitor.objects.get(pk=monitor_id)

    try:
        start = monitor.entries.earliest('timestamp').timestamp
    except monitor.entries.model.DoesNotExist:
        return  # no legacy entries at all

    try:
        end = monitor.pm25_entries.earliest().timestamp
    except entry_models.PM25.DoesNotExist:
        end = timezone.now()

    chunks = chunk_date_range(start, end, days=3)

    for chunk_start, chunk_end in chunks:
        copy_legacy_entries_range(monitor.pk, chunk_start, chunk_end)


@db_task()
def data_export(monitor_id, start_date, end_date, scope=None, email=None):
    try:
        monitor = Monitor.objects.get(pk=monitor_id)
    except Monitor.DoesNotExist:
        return {
            'status': 'error',
            'message': 'Monitor not found'
        }

    df = monitor.get_expanded_entries(
        start_time=datetime.combine(start_date, datetime.min.time()),
        end_time=datetime.combine(end_date + timedelta(days=1), datetime.min.time())
    )

    if df is None or df.empty:
        return {
            'status': 'error',
            'message': 'No data found for the given time range'
        }

    path = generate_export_path(monitor, start_date=start_date, end_date=end_date)
    path = default_storage.get_available_name(path)

    # Only ensure dirs for local filesystem
    if isinstance(default_storage, FileSystemStorage):
        full_path = default_storage.path(path)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)

    with default_storage.open(path, mode='w') as f:
        df.to_csv(f, index=False)

    url = default_storage.url(path)

    if email:
        send_email(
            subject=f'Your SJVAir data export for "{monitor.name}" is ready',
            template='email/entry-export-download.md',
            context={
                'url': url,
                'monitor': monitor,
                'start_date': start_date,
                'end_date': end_date,
            },
            to=email,
        )

    return {
        'status': 'complete',
        'url': url
    }
