"""Permanent removal: one document at once, and the daily sweep of expired trash and snapshots."""
from datetime import timedelta

from django.conf import settings
from django.db import transaction

from .models import DocumentSnapshot, PurgedDocument, SavedDocument


def purge_document(doc):
    """Delete the document (its log and snapshots cascade) and record that it was purged."""
    with transaction.atomic():
        PurgedDocument.objects.update_or_create(id=doc.id, defaults={'owner': doc.owner})
        doc.delete()


def purge_expired(now):
    """Purge documents deleted more than DOCUMENTS_TRASH_DAYS ago; returns how many."""
    cutoff = now - timedelta(days=settings.DOCUMENTS_TRASH_DAYS)
    count = 0
    for doc in SavedDocument.objects.filter(deleted_at__lt=cutoff).select_related('owner'):
        purge_document(doc)
        count += 1
    return count


def expire_snapshots(now):
    """Delete snapshots older than DOCUMENTS_SNAPSHOT_DAYS; returns how many."""
    cutoff = now - timedelta(days=settings.DOCUMENTS_SNAPSHOT_DAYS)
    deleted, _ = DocumentSnapshot.objects.filter(created_at__lt=cutoff).delete()
    return deleted
