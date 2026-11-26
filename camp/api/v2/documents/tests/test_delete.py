from datetime import timedelta
from unittest import mock

from django.test import Client, TestCase
from django.utils import timezone

from camp.apps.documents.models import DocumentChange, DocumentSnapshot, PurgedDocument, SavedDocument

from .. import endpoints
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
        assert response.status_code == 409
        assert response.json()['errors']['detail'][0]['code'] == 'not_deleted'
        assert response['Cache-Control'] == 'no-store'
        assert SavedDocument.objects.filter(pk='live').exists()
        assert not PurgedDocument.objects.exists()

    def test_delete_creates_purged_record_and_lists_it(self):
        doc = seed(self.alice, 'trash', deleted_at=timezone.now())
        DocumentChange.objects.create(document=doc, version=1, entries=[])
        DocumentSnapshot.objects.create(
            document=doc, owner=self.alice, version=1, schema_version=1, body={}, size=2,
            reason='daily',
        )
        before = (timezone.now() - timedelta(minutes=1)).isoformat()
        response = self.client.delete(f'{BASE}trash/')
        assert response.status_code == 204
        assert response['Cache-Control'] == 'no-store'
        assert not SavedDocument.objects.filter(pk='trash').exists()
        assert not DocumentChange.objects.exists()
        assert not DocumentSnapshot.objects.exists()
        assert PurgedDocument.objects.get(pk='trash').owner == self.alice
        data = self.client.get(BASE, {'since': before}).json()['data']
        assert data['purged'] == ['trash']
        assert self.client.get(f'{BASE}trash/').status_code == 410

    def test_delete_other_owner_not_found(self):
        seed(self.bob, 'theirs', deleted_at=timezone.now())
        response = self.client.delete(f'{BASE}theirs/')
        missing = self.client.delete(f'{BASE}nothing/')
        assert response.status_code == 404
        assert response.content == missing.content
        assert SavedDocument.objects.filter(pk='theirs').exists()
        assert not PurgedDocument.objects.exists()

    def test_delete_restored_after_read_is_not_deleted(self):
        seed(self.alice, 'trash', deleted_at=timezone.now())
        real = endpoints.owned_document

        def read_then_restore(request, id):
            doc = real(request, id)
            SavedDocument.objects.filter(pk=id).update(deleted_at=None)  # a restore lands
            return doc

        with mock.patch.object(endpoints, 'owned_document', side_effect=read_then_restore):
            response = self.client.delete(f'{BASE}trash/')
        assert response.status_code == 409
        assert response.json()['errors']['detail'][0]['code'] == 'not_deleted'
        assert SavedDocument.objects.filter(pk='trash').exists()
        assert not PurgedDocument.objects.exists()
