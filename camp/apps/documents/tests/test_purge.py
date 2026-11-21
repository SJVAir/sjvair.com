from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from camp.api.v2.documents.tests.helpers import make_user
from camp.api.v2.documents.tests.test_read import seed
from camp.apps.documents import purge
from camp.apps.documents.models import DocumentSnapshot, PurgedDocument, SavedDocument


class PurgeTests(TestCase):
    def setUp(self):
        self.alice = make_user(1)
        self.now = timezone.now()

    def test_purge_expired_only_older_than_30_days(self):
        seed(self.alice, 'old', deleted_at=self.now - timedelta(days=31))
        seed(self.alice, 'recent', deleted_at=self.now - timedelta(days=29))
        seed(self.alice, 'live')
        assert purge.purge_expired(self.now) == 1
        assert set(SavedDocument.objects.values_list('id', flat=True)) == {'recent', 'live'}
        assert list(PurgedDocument.objects.values_list('id', flat=True)) == ['old']

    def test_expire_snapshots_30_days(self):
        doc = seed(self.alice, 'doc')
        kept = []
        for age in (31, 29):
            snap = DocumentSnapshot.objects.create(
                document=doc, owner=self.alice, version=1, schema_version=1, body={}, size=2,
                reason='daily',
            )
            DocumentSnapshot.objects.filter(pk=snap.pk).update(
                created_at=self.now - timedelta(days=age)
            )
            kept.append(snap.pk)
        assert purge.expire_snapshots(self.now) == 1
        assert list(DocumentSnapshot.objects.values_list('pk', flat=True)) == [kept[1]]

    def test_purge_skips_a_document_restored_after_it_was_read(self):
        doc = seed(self.alice, 'doc', deleted_at=self.now - timedelta(days=1))
        SavedDocument.objects.filter(pk='doc').update(deleted_at=None)  # restored since the read
        assert not purge.purge_document(doc)
        assert SavedDocument.objects.get(pk='doc').deleted_at is None
        assert not PurgedDocument.objects.exists()

    def test_purge_skips_a_document_already_gone(self):
        doc = seed(self.alice, 'doc', deleted_at=self.now)
        SavedDocument.objects.filter(pk='doc').delete()
        assert not purge.purge_document(doc)
        assert not PurgedDocument.objects.exists()

    def test_sweep_skips_documents_restored_or_retrashed_mid_sweep(self):
        for id in ('restored', 'retrashed', 'expired'):
            seed(self.alice, id, deleted_at=self.now - timedelta(days=31))
        real = purge.purge_document

        def change_then_purge(doc, **kwargs):
            # What a save landing between the sweep's read and its purge would do.
            if doc.pk == 'restored':
                SavedDocument.objects.filter(pk=doc.pk).update(deleted_at=None)
            if doc.pk == 'retrashed':
                SavedDocument.objects.filter(pk=doc.pk).update(deleted_at=self.now)
            return real(doc, **kwargs)

        with mock.patch.object(purge, 'purge_document', side_effect=change_then_purge):
            assert purge.purge_expired(self.now) == 1
        assert set(SavedDocument.objects.values_list('id', flat=True)) == {'restored', 'retrashed'}
        assert list(PurgedDocument.objects.values_list('id', flat=True)) == ['expired']
