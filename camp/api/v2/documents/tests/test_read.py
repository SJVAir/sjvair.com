import json
from datetime import timedelta

from django.db import connection
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from camp.apps.documents.models import PurgedDocument, SavedDocument

from .helpers import BASE, body_queries, make_user


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
        assert response.status_code == 401
        assert Client().get(f'{BASE}abc/').status_code == 401

    def test_list_own_only(self):
        seed(self.alice, 'mine')
        seed(self.bob, 'theirs')
        data = self.client.get(BASE).json()['data']
        assert [d['id'] for d in data['documents']] == ['mine']
        assert data['purged'] == []
        assert 'cursor' in data
        meta = data['documents'][0]
        assert meta['size'] == 7
        assert 'body' not in meta
        assert set(meta) == {'id', 'kind', 'name', 'schema_version', 'version', 'copied_from', 'deleted_at',
            'created_at', 'updated_at', 'visibility', 'share_token', 'size'}

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
        assert [d['id'] for d in data['documents']] == ['new']
        assert data['purged'] == ['gone']
        # Without since: everything, and no purged list.
        data = self.client.get(BASE).json()['data']
        assert {d['id'] for d in data['documents']} == {'old', 'new'}
        assert data['purged'] == []

    def test_list_naive_since_is_treated_as_utc(self):
        old = seed(self.alice, 'old')
        seed(self.alice, 'new')
        SavedDocument.objects.filter(pk=old.pk).update(
            updated_at=timezone.now() - timedelta(days=2)
        )
        since = (timezone.now() - timedelta(days=1)).strftime('%Y-%m-%dT%H:%M:%S')
        response = self.client.get(BASE, {'since': since})
        assert response.status_code == 200
        assert [d['id'] for d in response.json()['data']['documents']] == ['new']

    def test_list_never_reads_bodies(self):
        seed(self.alice, 'mine')
        with CaptureQueriesContext(connection) as captured:
            assert self.client.get(BASE).status_code == 200
        assert body_queries(captured) == []

    def test_list_bad_since_is_invalid(self):
        # The second looks like a date and time but is no real day (Django raises on it).
        for since in ('yesterday-ish', '2026-02-30T00:00:00', '2026-13-01T25:00:00Z'):
            with self.subTest(since=since):
                response = self.client.get(BASE, {'since': since})
                assert response.status_code == 400
                payload = response.json()
                assert payload['errors']['detail'][0]['code'] == 'invalid'
                assert 'since' in payload['data']['fields']

    def test_cursor_is_ten_seconds_back(self):
        before = timezone.now()
        cursor = self.client.get(BASE).json()['data']['cursor']
        delta = before - parse_datetime(cursor)
        assert delta > timedelta(seconds=9)
        assert delta < timedelta(seconds=12)

    def test_list_includes_deleted(self):
        seed(self.alice, 'trashed', deleted_at=timezone.now())
        data = self.client.get(BASE).json()['data']
        assert [d['id'] for d in data['documents']] == ['trashed']
        assert data['documents'][0]['deleted_at'] is not None

    def test_detail_returns_document(self):
        seed(self.alice, 'mine', name='Mine')
        response = self.client.get(f'{BASE}mine/')
        assert response.status_code == 200
        doc = response.json()['data']
        assert doc['body'] == {'a': 1}
        assert doc['name'] == 'Mine'
        assert doc['version'] == 1
        assert 'size' not in doc

    def test_detail_other_owner_same_as_missing(self):
        seed(self.bob, 'theirs')
        other = self.client.get(f'{BASE}theirs/')
        missing = self.client.get(f'{BASE}never-used/')
        assert other.status_code == 404
        assert other.status_code == missing.status_code
        assert other.content == missing.content
        assert other.json()['errors']['detail'][0]['code'] == 'not_found'

    def test_detail_purged_is_gone(self):
        PurgedDocument.objects.create(id='bye', owner=self.alice)
        response = self.client.get(f'{BASE}bye/')
        assert response.status_code == 410
        assert response.json()['errors']['detail'][0]['code'] == 'gone'

    def test_detail_purged_of_other_user_is_not_found(self):
        PurgedDocument.objects.create(id='bye', owner=self.bob)
        assert self.client.get(f'{BASE}bye/').status_code == 404

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
            assert response['Cache-Control'] == 'no-store', response.status_code
