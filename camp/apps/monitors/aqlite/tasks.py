from datetime import timedelta

from django.utils import timezone

from django_huey import db_task, db_periodic_task
from huey import crontab

from camp.apps.monitors.aqlite.models import AQLite


@db_periodic_task(crontab(minute='*/5'), priority=50)
def update_realtime():
    start = timezone.now()
    print(f'\n=== AQLite Import Start: {start.time()}\n')

    monitors = (AQLite.objects
        .select_related('organization')
        .filter(organization__isnull=False, organization__is_enabled=True)
        .get_active()
    )

    for monitor in monitors:
        process_data.schedule([monitor.pk], delay=1, priority=40)

    end = timezone.now()
    print(f'\n=== AQLite Import Done: {start.time()} - {end.time()} ({end - start})\n')


@db_task()
def process_data(monitor_id):
    monitor = AQLite.objects.select_related('organization').get(pk=monitor_id)

    end = timezone.now()
    start = end - timedelta(minutes=10)

    response = monitor.organization.api.get_time_series(
        device_id=monitor.device_id,
        start=start,
        end=end,
        average=0,
    )

    for payload in monitor.parse_response(response):
        entries = monitor.create_entries(payload)
        for entry in entries:
            monitor.process_entry_pipeline(entry)

    monitor.save()
