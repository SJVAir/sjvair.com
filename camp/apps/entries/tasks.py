import os

from django.conf import settings
from django.core.files.storage import default_storage, FileSystemStorage
from django.core.mail import send_mail

from django_huey import db_task

from camp.apps.entries.utils import generate_export_path
from camp.apps.monitors.models import Monitor


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
        send_mail(
            subject='Your SJVAir data export is ready',
            message=f'Your requested data export is ready. Download it here:\n\n{url}',
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[email],
        )

    return {
        'status': 'complete',
        'url': url
    }
