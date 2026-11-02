import json
from datetime import timedelta

from django.db import connection
from django.core.cache import cache
from django.test import Client, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from camp.apps.documents.models import (
    BlockedBuild, DocumentChange, DocumentSnapshot, PurgedDocument, SavedDocument, measure,
)

from .helpers import (
    BASE, MISSING, account_id, body, body_queries, code, frozen_clock, make_user, padded_body,
    post_snapshot, save,
)


def seed(owner, id):
    return SavedDocument.objects.create(
        id=id, owner=owner, kind='dashboard', name=id, body={'a': 1}, size=7, schema_version=1,
        version=2,
    )


def snap(doc, version, reason='daily', age=0):
    made = DocumentSnapshot.objects.create(
        document=doc, owner=doc.owner, version=version, schema_version=1, name=f'v{version}',
        body={'v': version}, size=9, reason=reason,
    )
    DocumentSnapshot.objects.filter(pk=made.pk).update(
        created_at=timezone.now() - timedelta(days=age)
    )
    return made


class SnapshotReadTests(TestCase):
    def setUp(self):
        self.alice = make_user(1)
        self.bob = make_user(2)
        self.client = Client()
        self.client.force_login(self.alice)

    def test_snapshot_list_newest_first(self):
        doc = seed(self.alice, 'd')
        old = snap(doc, 1, 'daily', age=2)
        new = snap(doc, 2, 'conflict', age=0)
        response = self.client.get(f'{BASE}d/snapshots/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Cache-Control'], 'no-store')
        rows = response.json()['data']
        self.assertEqual([r['id'] for r in rows], [new.id, old.id])
        self.assertEqual(
            set(rows[0]), {'id', 'version', 'schema_version', 'reason', 'created_at'}
        )
        self.assertEqual(rows[0]['reason'], 'conflict')

    def test_snapshot_list_never_reads_bodies(self):
        doc = seed(self.alice, 'd')
        snap(doc, 1)
        with CaptureQueriesContext(connection) as captured:
            self.assertEqual(self.client.get(f'{BASE}d/snapshots/').status_code, 200)
        self.assertEqual(body_queries(captured), [])

    def test_snapshot_detail(self):
        doc = seed(self.alice, 'd')
        made = snap(doc, 1)
        data = self.client.get(f'{BASE}d/snapshots/{made.id}/').json()['data']
        self.assertEqual(
            set(data), {'id', 'version', 'schema_version', 'name', 'body', 'created_at'}
        )
        self.assertEqual(data['body'], {'v': 1})
        self.assertEqual(data['name'], 'v1')

    def test_snapshot_detail_other_owner_not_found(self):
        theirs = seed(self.bob, 'theirs')
        made = snap(theirs, 1)
        mine = seed(self.alice, 'mine')
        mine_snap = snap(mine, 1)
        missing = self.client.get(f'{BASE}nope/snapshots/{made.id}/')
        other = self.client.get(f'{BASE}theirs/snapshots/{made.id}/')
        self.assertEqual(other.status_code, 404)
        self.assertEqual(other.content, missing.content)
        # A snapshot id that exists but belongs to a different document of mine.
        wrong_doc = self.client.get(f'{BASE}mine/snapshots/{made.id}/')
        self.assertEqual(wrong_doc.status_code, 404)
        self.assertEqual(wrong_doc.content, missing.content)
        self.assertEqual(self.client.get(f'{BASE}mine/snapshots/{mine_snap.id}/').status_code, 200)
        listing = self.client.get(f'{BASE}theirs/snapshots/')
        self.assertEqual(listing.status_code, 404)
        self.assertEqual(listing.content, self.client.get(f'{BASE}nope/snapshots/').content)

    def test_signed_out_401(self):
        self.assertEqual(Client().get(f'{BASE}d/snapshots/').status_code, 401)


FIVE_KEYS = {'id', 'version', 'schema_version', 'reason', 'created_at'}


class SnapshotPostTests(TestCase):
    def setUp(self):
        cache.clear()
        self.alice = make_user(1)
        self.bob = make_user(2)
        self.client = Client()
        self.client.force_login(self.alice)
        assert save(self.client, 'd', name='Stored', body=body(0)).status_code == 200

    def post(self, id='d', **overrides):
        response = post_snapshot(self.client, id, **overrides)
        assert response['Cache-Control'] == 'no-store'
        return response

    def fields(self, response):
        assert response.status_code == 400
        assert code(response) == 'invalid'
        return response.json()['data']['fields']

    def test_keeps_given_content_as_conflict(self):
        response = self.post()
        assert response.status_code == 201
        data = response.json()['data']
        assert set(data) == FIVE_KEYS
        assert (data['reason'], data['version'], data['schema_version']) == ('conflict', 1, 1)
        stored = DocumentSnapshot.objects.get(pk=data['id'])
        assert (stored.name, stored.body, stored.size) == ('Mine', body(1), measure(body(1)))
        assert stored.owner == self.alice

    def test_document_untouched(self):
        doc = SavedDocument.objects.get(pk='d')
        before = (doc.version, doc.updated_at, doc.body, doc.name, DocumentChange.objects.count())
        assert self.post().status_code == 201
        doc.refresh_from_db()
        assert (doc.version, doc.updated_at, doc.body, doc.name,
                DocumentChange.objects.count()) == before

    def test_listed_in_snapshot_list(self):
        made = self.post().json()['data']
        rows = self.client.get(f'{BASE}d/snapshots/').json()['data']
        assert rows[0]['id'] == made['id']

    def test_missing_field_is_invalid(self):
        assert self.fields(self.post(name=MISSING)) == {'name': ['This field is required.']}
        assert not DocumentSnapshot.objects.exists()

    def test_null_name_accepted(self):
        assert self.post(name=None).status_code == 201

    def test_base_version_must_be_int(self):
        for value in (None, True, -1, '1'):
            with self.subTest(value=value):
                fields = self.fields(self.post(base_version=value))
                assert fields == {'base_version': ['Must be an integer >= 0.']}

    def test_non_object_request_is_invalid(self):
        response = self.client.post(
            f'{BASE}d/snapshots/', json.dumps([1]), content_type='application/json'
        )
        assert 'request' in self.fields(response)

    def test_body_must_be_json_object(self):
        assert 'body' in self.fields(self.post(body=[1]))

    def test_bad_id_is_invalid(self):
        assert 'id' in self.fields(self.post(id='profile'))

    @override_settings(DOCUMENTS_MAX_BODY=10)
    def test_too_large(self):
        response = self.post()
        assert (response.status_code, code(response)) == (413, 'too_large')
        assert not DocumentSnapshot.objects.exists()

    @override_settings(DOCUMENTS_MAX_BODY=10)
    def test_invalid_before_too_large_before_blocked(self):
        assert code(self.post(name='x' * 101)) == 'invalid'
        BlockedBuild.objects.create(build_id='test-build')
        assert code(self.post()) == 'too_large'

    def test_build_blocked(self):
        BlockedBuild.objects.create(build_id='test-build')
        response = self.post()
        assert (response.status_code, code(response)) == (409, 'build_blocked')

    def test_account_mismatch(self):
        response = self.post(account_id='nope')
        assert (response.status_code, code(response)) == (403, 'account_mismatch')
        assert response.json()['data'] == {'signed_in_as': account_id(self.client)}

    @override_settings(DOCUMENTS_SAVES_PER_MINUTE=2)
    def test_rate_limit_shared_with_saves(self):
        with frozen_clock():
            assert save(self.client, 'e').status_code == 200
            assert self.post().status_code == 201
            response = self.post()
        assert (response.status_code, code(response)) == (429, 'rate_limited')
        assert DocumentSnapshot.objects.count() == 1

    def test_not_found_and_not_yours_identical(self):
        SavedDocument.objects.create(
            id='theirs', owner=self.bob, kind='dashboard', body={}, size=2, schema_version=1,
            version=1,
        )
        missing = self.post(id='nope')
        theirs = self.post(id='theirs')
        assert (missing.status_code, code(missing)) == (404, 'not_found')
        assert theirs.status_code == 404
        assert theirs.content == missing.content
        assert not DocumentSnapshot.objects.exists()

    def test_own_purged_is_gone(self):
        PurgedDocument.objects.create(id='gone-doc', owner=self.alice)
        response = self.post(id='gone-doc')
        assert (response.status_code, code(response)) == (410, 'gone')

    def test_stale_base_payload_matches_save(self):
        response = self.post(base_version=0)
        assert (response.status_code, code(response)) == (409, 'stale_base')
        from_save = save(self.client, 'd', base_version=0)
        assert response.json()['data'] == from_save.json()['data']
        assert response.json()['data']['document']['body'] == body(0)
        assert not DocumentSnapshot.objects.exists()

    def test_older_schema_and_trashed_accepted(self):
        response = save(
            self.client, 'd', base_version=1, schema_version=2,
            deleted_at='2026-11-02T00:00:00Z',
        )
        assert response.status_code == 200
        assert self.post(base_version=2, schema_version=1).status_code == 201

    def test_over_snapshot_cap_still_201_and_trims(self):
        with override_settings(DOCUMENTS_MAX_SNAPSHOT_STORAGE=measure(body(1)) * 2):
            ids = [self.post().json()['data']['id'] for _ in range(3)]
        assert list(DocumentSnapshot.objects.order_by('pk').values_list('pk', flat=True)) == ids[1:]

    def test_success_never_reads_document_body(self):
        with CaptureQueriesContext(connection) as captured:
            assert self.post().status_code == 201
        reads = [sql for sql in body_queries(captured) if 'documents_saveddocument' in sql]
        assert reads == []

    @override_settings(DATA_UPLOAD_MAX_MEMORY_SIZE=1000)
    def test_large_session_body_accepted(self):
        assert self.post(body=padded_body(2000)).status_code == 201

    @override_settings(DOCUMENTS_MAX_REQUEST_BYTES=1000)
    def test_over_request_cap_is_too_large(self):
        response = self.post(body=padded_body(2000))
        assert (response.status_code, code(response)) == (413, 'too_large')
        assert not DocumentSnapshot.objects.exists()

    def test_account_checked_before_document(self):
        response = self.post(id='nope', account_id='other')
        assert (response.status_code, code(response)) == (403, 'account_mismatch')

    def test_posted_snapshot_does_not_suppress_daily(self):
        assert self.post().status_code == 201
        assert save(self.client, 'd', base_version=1).status_code == 200
        reasons = list(DocumentSnapshot.objects.order_by('pk').values_list('reason', 'version'))
        assert reasons == [('conflict', 1), ('daily', 1)]

    def test_signed_out_401(self):
        assert post_snapshot(Client(), 'd').status_code == 401
