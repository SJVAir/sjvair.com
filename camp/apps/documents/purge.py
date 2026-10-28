"""Permanent removal: one document at once, and the daily sweep of expired trash and snapshots."""
from datetime import timedelta

from django.conf import settings
from django.db import transaction

from .models import DocumentSnapshot, PurgedDocument, SavedDocument


def purge_document(doc, cutoff=None):
    """Delete the document (its log and snapshots cascade) and record that it was purged.

    `doc` may be stale: the row is locked and checked again first, so a document restored (or,
    with `cutoff`, trashed again later) since it was read is left alone, never losing that save.
    Returns whether the document was purged.
    """
    with transaction.atomic():
        rows = SavedDocument.objects.select_for_update().filter(
            pk=doc.pk, deleted_at__isnull=False
        )
        if cutoff is not None:
            rows = rows.filter(deleted_at__lt=cutoff)
        locked = rows.only('id', 'owner_id').first()
        if locked is None:
            return False
        PurgedDocument.objects.update_or_create(
            id=locked.id, defaults={'owner_id': locked.owner_id}
        )
        locked.delete()
    return True


def purge_expired(now):
    """Purge documents deleted more than DOCUMENTS_TRASH_DAYS ago; returns how many."""
    cutoff = now - timedelta(days=settings.DOCUMENTS_TRASH_DAYS)
    count = 0
    for doc in SavedDocument.objects.filter(deleted_at__lt=cutoff).only('pk'):
        if purge_document(doc, cutoff=cutoff):
            count += 1
    return count


def expire_snapshots(now):
    """Delete snapshots older than DOCUMENTS_SNAPSHOT_DAYS; returns how many."""
    cutoff = now - timedelta(days=settings.DOCUMENTS_SNAPSHOT_DAYS)
    deleted, _ = DocumentSnapshot.objects.filter(created_at__lt=cutoff).delete()
    return deleted
