from datetime import timedelta

from django.test import Client, TestCase
from django.utils import timezone

from camp.apps.documents.models import DocumentChange, DocumentSnapshot, PurgedDocument, SavedDocument

from .helpers import BASE, make_user
from .test_read import seed


class DeleteTests(TestCase):
    def setUp(self):
        self.alice = make_user(1)
        self.bob = make_user(2)
        self.client = Client()
        self.client.force_login(self.alice)

    def test_delete_requires_deleted_at(self):
        seed(self.alice, 'live')
        response = self.client.delete(f'{BASE}live/')
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()['errors']['detail'][0]['code'], 'not_deleted')
        self.assertEqual(response['Cache-Control'], 'no-store')
        self.assertTrue(SavedDocument.objects.filter(pk='live').exists())
        self.assertFalse(PurgedDocument.objects.exists())

    def test_delete_creates_purged_record_and_lists_it(self):
        doc = seed(self.alice, 'trash', deleted_at=timezone.now())
        DocumentChange.objects.create(document=doc, version=1, entries=[])
        DocumentSnapshot.objects.create(
            document=doc, owner=self.alice, version=1, schema_version=1, body={}, size=2,
            reason='daily',
        )
        before = (timezone.now() - timedelta(minutes=1)).isoformat()
        response = self.client.delete(f'{BASE}trash/')
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response['Cache-Control'], 'no-store')
        self.assertFalse(SavedDocument.objects.filter(pk='trash').exists())
        self.assertFalse(DocumentChange.objects.exists())
        self.assertFalse(DocumentSnapshot.objects.exists())
        self.assertEqual(PurgedDocument.objects.get(pk='trash').owner, self.alice)
        data = self.client.get(BASE, {'since': before}).json()['data']
        self.assertEqual(data['purged'], ['trash'])
        self.assertEqual(self.client.get(f'{BASE}trash/').status_code, 410)

    def test_delete_other_owner_not_found(self):
        seed(self.bob, 'theirs', deleted_at=timezone.now())
        response = self.client.delete(f'{BASE}theirs/')
        missing = self.client.delete(f'{BASE}nothing/')
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.content, missing.content)
        self.assertTrue(SavedDocument.objects.filter(pk='theirs').exists())
        self.assertFalse(PurgedDocument.objects.exists())
