import json
from datetime import timedelta

from django.test import Client, TestCase
from django.utils import timezone

from camp.apps.documents.models import PurgedDocument, SavedDocument

from .helpers import BASE, make_user


def seed(owner, id, **extra):
    fields = dict(
        id=id, owner=owner, kind='dashboard', name=id, body={'a': 1}, size=7, schema_version=1,
        version=1,
    )
    fields.update(extra)
    return SavedDocument.objects.create(**fields)


class ReadTests(TestCase):
    def setUp(self):
        self.alice = make_user(1)
        self.bob = make_user(2)
        self.client = Client()
        self.client.force_login(self.alice)

    def test_signed_out_401(self):
        response = Client().get(BASE)
        self.assertEqual(response.status_code, 401)
        self.assertEqual(Client().get(f'{BASE}abc/').status_code, 401)

    def test_list_own_only(self):
        seed(self.alice, 'mine')
        seed(self.bob, 'theirs')
        data = self.client.get(BASE).json()['data']
        self.assertEqual([d['id'] for d in data['documents']], ['mine'])
        self.assertEqual(data['purged'], [])
        self.assertIn('cursor', data)
        meta = data['documents'][0]
        self.assertEqual(meta['size'], 7)
        self.assertNotIn('body', meta)
        self.assertEqual(
            set(meta),
            {'id', 'kind', 'name', 'schema_version', 'version', 'copied_from', 'deleted_at',
             'created_at', 'updated_at', 'visibility', 'share_token', 'size'},
        )

    def test_list_since_returns_changed_and_purged(self):
        old = seed(self.alice, 'old')
        new = seed(self.alice, 'new')
        past = timezone.now() - timedelta(days=2)
        SavedDocument.objects.filter(pk=old.pk).update(updated_at=past)
        gone = PurgedDocument.objects.create(id='gone', owner=self.alice)
        PurgedDocument.objects.create(id='ancient', owner=self.alice)
        PurgedDocument.objects.filter(id='ancient').update(purged_at=past)
        since = (timezone.now() - timedelta(days=1)).isoformat()
        data = self.client.get(BASE, {'since': since}).json()['data']
        self.assertEqual([d['id'] for d in data['documents']], ['new'])
        self.assertEqual(data['purged'], ['gone'])
        # Without since: everything, and no purged list.
        data = self.client.get(BASE).json()['data']
        self.assertEqual({d['id'] for d in data['documents']}, {'old', 'new'})
        self.assertEqual(data['purged'], [])

    def test_list_bad_since_is_invalid(self):
        response = self.client.get(BASE, {'since': 'yesterday-ish'})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['errors']['detail'][0]['code'], 'invalid')

    def test_cursor_is_ten_seconds_back(self):
        before = timezone.now()
        cursor = self.client.get(BASE).json()['data']['cursor']
        from django.utils.dateparse import parse_datetime

        delta = before - parse_datetime(cursor)
        self.assertGreater(delta, timedelta(seconds=9))
        self.assertLess(delta, timedelta(seconds=12))

    def test_list_includes_deleted(self):
        seed(self.alice, 'trashed', deleted_at=timezone.now())
        data = self.client.get(BASE).json()['data']
        self.assertEqual([d['id'] for d in data['documents']], ['trashed'])
        self.assertIsNotNone(data['documents'][0]['deleted_at'])

    def test_detail_returns_document(self):
        seed(self.alice, 'mine', name='Mine')
        response = self.client.get(f'{BASE}mine/')
        self.assertEqual(response.status_code, 200)
        doc = response.json()['data']
        self.assertEqual(doc['body'], {'a': 1})
        self.assertEqual(doc['name'], 'Mine')
        self.assertEqual(doc['version'], 1)
        self.assertNotIn('size', doc)

    def test_detail_other_owner_same_as_missing(self):
        seed(self.bob, 'theirs')
        other = self.client.get(f'{BASE}theirs/')
        missing = self.client.get(f'{BASE}never-used/')
        self.assertEqual(other.status_code, 404)
        self.assertEqual(other.status_code, missing.status_code)
        self.assertEqual(other.content, missing.content)
        self.assertEqual(other.json()['errors']['detail'][0]['code'], 'not_found')

    def test_detail_purged_is_gone(self):
        PurgedDocument.objects.create(id='bye', owner=self.alice)
        response = self.client.get(f'{BASE}bye/')
        self.assertEqual(response.status_code, 410)
        self.assertEqual(response.json()['errors']['detail'][0]['code'], 'gone')

    def test_detail_purged_of_other_user_is_not_found(self):
        PurgedDocument.objects.create(id='bye', owner=self.bob)
        self.assertEqual(self.client.get(f'{BASE}bye/').status_code, 404)

    def test_no_store_on_success_and_error(self):
        seed(self.alice, 'mine')
        PurgedDocument.objects.create(id='bye', owner=self.alice)
        for response in [
            self.client.get(BASE),
            self.client.get(f'{BASE}mine/'),
            self.client.get(f'{BASE}nope/'),
            self.client.get(f'{BASE}bye/'),
            self.client.delete(f'{BASE}mine/'),  # 405 from resticus
            Client().get(BASE),  # 401 from resticus
        ]:
            self.assertEqual(response['Cache-Control'], 'no-store', response.status_code)
