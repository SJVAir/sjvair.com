import os

from django.conf import settings
from django.core.files.storage import default_storage, FileSystemStorage

from django_huey import db_task

from camp.apps.entries import models as entry_models
from camp.apps.entries.utils import generate_export_path
from camp.apps.monitors.models import Monitor
from camp.utils.email import send_email


@db_task(queue='secondary')
def copy_legacy_entries(monitor_id):
    monitor = Monitor.objects.get(pk=monitor_id)

    queryset = monitor.entries.all()
    try:
        earliest = monitor.pm25_entries.earliest().timestamp
        queryset = queryset.filter(timestamp__lt=earliest)
    except entry_models.PM25.DoesNotExist:
        pass

    for i, entry in enumerate(queryset.iterator()):
        print(i, entry.timestamp)
        new_entries = []

        if entry.pm25 is not None:
            if new := monitor.create_entry(entry_models.PM25,
                value=entry.pm25,
                timestamp=entry.timestamp
            ):
                new_entries.append(new)

        if entry.fahrenheit is not None:
            if new := monitor.create_entry(entry_models.Temperature,
                value=entry.fahrenheit,
                timestamp=entry.timestamp
            ):
                new_entries.append(new)

        if entry.humidity is not None:
            if new := monitor.create_entry(entry_models.Humidity,
                value=entry.humidity,
                timestamp=entry.timestamp
            ):
                new_entries.append(new)

        if entry.ozone is not None:
            if new := monitor.create_entry(entry_models.O3,
                value=entry.ozone,
                timestamp=entry.timestamp
            ):
                new_entries.append(new)

        monitor.process_entries_ng(new_entries)


@db_task()
def data_export(monitor_id, start_date, end_date, email=None):
    try:
        monitor = Monitor.objects.get(pk=monitor_id)
    except Monitor.DoesNotExist:
        return {
            'status': 'error',
            'message': 'Monitor not found'
        }

    df = monitor.get_entry_data_table(start_date=start_date, end_date=end_date)

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
