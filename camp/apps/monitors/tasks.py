from huey.contrib.djhuey import db_task

from .models import Entry, Monitor


@db_task()
def process_entry(entry_id):
    entry = Entry.objects.get(pk=entry_id)
    monitor = Monitor.objects.get(pk=entry.monitor_id)
    monitor.process_entry(entry)
    entry.save()
