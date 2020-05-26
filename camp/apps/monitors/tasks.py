from django.db.models import F, OuterRef, Subquery

from huey import crontab
from huey.contrib.djhuey import db_task, db_periodic_task

from camp.apps.monitors.models import Entry, Monitor


# @db_periodic_task(crontab(minute='*'))
# def update_latest_entries():
#     print('[update_latest_entries]')
#     Monitor.objects.annotate(
#         latest_entry=Subquery(
#             Entry.objects.filter(monitor_id=OuterRef('pk'), is_processed=True).order_by('-timestamp').values('pk')[:1]
#         )
#     ).update(latest_id=F('latest_entry'))
