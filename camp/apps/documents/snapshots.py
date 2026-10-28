"""Snapshots of a document's stored state, taken just before a save overwrites it."""
from datetime import datetime
from zoneinfo import ZoneInfo

from django.conf import settings
from django.db.models import Sum

from .models import DocumentSnapshot

PACIFIC = ZoneInfo('America/Los_Angeles')


def start_of_day(now):
    """Midnight Pacific at the start of the day containing `now`."""
    local = now.astimezone(PACIFIC)
    return datetime.combine(local.date(), datetime.min.time(), tzinfo=PACIFIC)


def reason_for(doc, cleaned, now):
    """Why this save should snapshot the stored state of `doc`, or None. One reason at most."""
    if cleaned['schema_version'] > doc.schema_version:
        return DocumentSnapshot.Reason.SCHEMA
    if cleaned['snapshot'] == 'conflict':
        return DocumentSnapshot.Reason.CONFLICT
    if not doc.snapshots.filter(created_at__gte=start_of_day(now)).exists():
        return DocumentSnapshot.Reason.DAILY
    return None


def take(doc, reason):
    """Copy the stored state of `doc`, then trim the owner's oldest snapshots to the cap."""
    snapshot = DocumentSnapshot.objects.create(
        document=doc, owner_id=doc.owner_id, version=doc.version,
        schema_version=doc.schema_version, name=doc.name, body=doc.body, size=doc.size,
        reason=reason,
    )
    trim(doc.owner_id)
    return snapshot


def trim(owner_id):
    mine = DocumentSnapshot.objects.filter(owner_id=owner_id)
    total = mine.aggregate(total=Sum('size'))['total'] or 0
    if total <= settings.DOCUMENTS_MAX_SNAPSHOT_STORAGE:
        return
    for pk, size in mine.order_by('created_at', 'pk').values_list('pk', 'size'):
        if total <= settings.DOCUMENTS_MAX_SNAPSHOT_STORAGE:
            break
        DocumentSnapshot.objects.filter(pk=pk).delete()
        total -= size
