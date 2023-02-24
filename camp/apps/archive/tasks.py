from datetime import timedelta

from django.utils import timezone

from huey import crontab
from huey.contrib.djhuey import db_periodic_task, db_task

from camp.apps.archive.models import EntryArchive
from camp.apps.monitors.models import Monitor


@db_task()
def create_entry_archive(monitor_id, year, month):
    monitor = Monitor.objects.get(pk=monitor_id)
    print(f'Archiving entries: {monitor.name} ({year}-{month})')
    EntryArchive.objects.generate(monitor=monitor, year=year, month=month)


# In the first day of the month at 12pm UTC, archive the last month of data.
@db_periodic_task(crontab(day='1', hour='12', minute='0'), priority=50)
def archive_last_month_entries():
    last_month = timezone.now().date().replace(day=1) - timedelta(hours=24)
    monitor_list = Monitor.objects.all()
    for monitor in monitor_list:
        create_entry_archive(monitor.pk, last_month.year, last_month.month, priority=1)
