from datetime import timedelta

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
        self.assertEqual(purge.purge_expired(self.now), 1)
        self.assertEqual(
            set(SavedDocument.objects.values_list('id', flat=True)), {'recent', 'live'}
        )
        self.assertEqual(list(PurgedDocument.objects.values_list('id', flat=True)), ['old'])

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
        self.assertEqual(purge.expire_snapshots(self.now), 1)
        self.assertEqual(list(DocumentSnapshot.objects.values_list('pk', flat=True)), [kept[1]])
