from django.utils import timezone

from django_huey import db_periodic_task
from huey import crontab

from . import purge


# Daily at 10:15 UTC (early morning Pacific): purge documents deleted over 30 days ago.
@db_periodic_task(crontab(hour='10', minute='15'))
def purge_expired_documents():
    count = purge.purge_expired(timezone.now())
    print(f'Purged {count} expired documents')


# Daily at 10:45 UTC: delete snapshots older than 30 days.
@db_periodic_task(crontab(hour='10', minute='45'))
def expire_document_snapshots():
    count = purge.expire_snapshots(timezone.now())
    print(f'Expired {count} document snapshots')
