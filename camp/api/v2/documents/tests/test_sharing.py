import json
from datetime import timedelta

from django.test import Client, TestCase
from django.utils import timezone

from camp.apps.documents.models import DocumentProfile, SavedDocument

from .helpers import BASE, make_user, save

# `id` lets "Make a copy" record copiedFrom; nothing here identifies the owner.
SHARED_KEYS = {
    'id', 'kind', 'name', 'schema_version', 'version', 'body', 'updated_at', 'display_name',
}


class SharingTests(TestCase):
    def setUp(self):
        self.alice = make_user(1)
        self.bob = make_user(2)
        self.client = Client()
        self.client.force_login(self.alice)
        self.anon = Client()

    def create(self, id='doc', **overrides):
        response = save(self.client, id, **overrides)
        assert response.status_code == 200
        return response

    def share(self, id='doc', client=None):
        return (client or self.client).post(f'{BASE}{id}/share/')

    def revoke(self, id='doc', client=None):
        return (client or self.client).delete(f'{BASE}{id}/share/')

    def token(self, id='doc'):
        response = self.share(id)
        assert response.status_code == 200
        return response.json()['data']['share_token']

    def shared(self, token, client=None):
        return (client or self.anon).get(f'{BASE}shared/{token}/')

    def shared_changes(self, token, **params):
        return self.anon.get(f'{BASE}shared/{token}/changes/', params)

    def credit(self, id='doc', client=None):
        return (client or self.anon).get(f'{BASE}{id}/credit/')

    def assert_unavailable(self, response):
        assert response.status_code == 404
        assert response.json()['errors']['detail'][0]['code'] == 'not_found'
        assert response['Cache-Control'] == 'no-store'

    def test_share_creates_token_of_22_plus_chars(self):
        self.create()
        response = self.share()
        assert response.status_code == 200
        assert response['Cache-Control'] == 'no-store'
        token = response.json()['data']['share_token']
        assert len(token) >= 22
        doc = SavedDocument.objects.get(pk='doc')
        assert doc.share_token == token
        assert doc.visibility == 'link'

    def listed_since(self, cursor):
        data = self.client.get(BASE, {'since': cursor.isoformat()}).json()['data']
        return {doc['id']: doc for doc in data['documents']}

    def age(self, id='doc'):
        """Make the document's last change an hour old, before the cursor below."""
        SavedDocument.objects.filter(pk=id).update(updated_at=timezone.now() - timedelta(hours=1))

    def test_share_and_revoke_reach_other_devices(self):
        self.create()
        self.age()
        cursor = timezone.now() - timedelta(minutes=1)
        assert 'doc' not in self.listed_since(cursor)

        token = self.token()
        listed = self.listed_since(cursor)['doc']
        assert (listed['visibility'], listed['share_token']) == ('link', token)
        assert listed['version'] == 1

        self.age()
        assert self.revoke().status_code == 204
        listed = self.listed_since(cursor)['doc']
        assert (listed['visibility'], listed['share_token']) == ('private', None)
        assert listed['version'] == 1

    def test_share_twice_same_token(self):
        self.create()
        assert self.token() == self.token()

    def test_share_others_or_missing_is_not_found(self):
        self.create()
        bob = Client()
        bob.force_login(self.bob)
        theirs = self.share(client=bob)
        missing = self.share('nope')
        self.assert_unavailable(theirs)
        assert theirs.content == missing.content
        self.assert_unavailable(self.revoke(client=bob))
        assert SavedDocument.objects.get(pk='doc').share_token is None

    def test_share_deleted_is_not_found(self):
        self.create(deleted_at='2026-10-28T00:00:00Z')
        self.assert_unavailable(self.share())

    def test_share_requires_login(self):
        self.create()
        assert self.share(client=self.anon).status_code == 401
        assert self.revoke(client=self.anon).status_code == 401

    def test_revoke_then_share_new_token_old_dead(self):
        self.create()
        old = self.token()
        assert self.shared(old).status_code == 200

        response = self.revoke()
        assert response.status_code == 204
        assert response['Cache-Control'] == 'no-store'
        doc = SavedDocument.objects.get(pk='doc')
        assert doc.share_token is None
        assert doc.visibility == 'private'
        self.assert_unavailable(self.shared(old))

        new = self.token()
        assert new != old
        assert self.shared(new).status_code == 200
        self.assert_unavailable(self.shared(old))
        self.assert_unavailable(self.shared_changes(old, since=0))

    def test_soft_delete_hides_then_restore_same_link(self):
        self.create()
        token = self.token()
        self.create(base_version=1, deleted_at='2026-10-28T00:00:00Z')
        unknown = self.shared('no-such-token-at-all-xx')
        hidden = self.shared(token)
        self.assert_unavailable(hidden)
        assert hidden.content == unknown.content

        self.create(base_version=2, deleted_at=None)
        restored = self.shared(token)
        assert restored.status_code == 200
        assert restored.json()['data']['version'] == 3
        assert SavedDocument.objects.get(pk='doc').share_token == token

    def test_not_shareable_responses_identical(self):
        tokens = {}

        self.create('private')
        SavedDocument.objects.filter(pk='private').update(share_token='tok-private-0000000000')
        tokens['private'] = 'tok-private-0000000000'

        self.create('revoked')
        tokens['revoked'] = self.token('revoked')
        self.revoke('revoked')

        self.create('deleted')
        tokens['deleted'] = self.token('deleted')
        self.create('deleted', base_version=1, deleted_at='2026-10-28T00:00:00Z')

        tokens['unknown'] = 'tok-unknown-0000000000'

        self.create('disabled')
        tokens['disabled'] = self.token('disabled')
        SavedDocument.objects.filter(pk='disabled').update(sharing_disabled=True)

        bob = Client()
        bob.force_login(self.bob)
        save(bob, 'blocked')
        tokens['blocked'] = self.token_for(bob, 'blocked')
        DocumentProfile.objects.create(user=self.bob, sharing_blocked=True)

        reads = {reason: self.shared(token) for reason, token in tokens.items()}
        polls = {reason: self.shared_changes(token, since=0) for reason, token in tokens.items()}
        for responses in (reads, polls):
            first = responses['unknown']
            self.assert_unavailable(first)
            for reason, response in responses.items():
                with self.subTest(reason=reason):
                    assert response.status_code == first.status_code
                    assert response.content == first.content
        assert reads['unknown'].content == polls['unknown'].content
        assert b'This shared dashboard is no longer available.' in reads['unknown'].content

    def token_for(self, client, id):
        response = self.share(id, client=client)
        assert response.status_code == 200
        return response.json()['data']['share_token']

    def assert_no_personal(self, response):
        content = response.content.decode()
        for value in (self.alice.email, self.alice.full_name, str(self.alice.phone)):
            assert value not in content
        data = response.json()['data']
        assert 'owner' not in data
        assert 'owner_id' not in data
        assert f'"{self.alice.pk}"' not in content

    def test_shared_has_no_personal_fields(self):
        self.create(name='Fresno air')
        token = self.token()
        response = self.shared(token)
        assert response.status_code == 200
        assert response['Cache-Control'] == 'no-store'
        data = response.json()['data']
        assert set(data) == SHARED_KEYS
        assert data['name'] == 'Fresno air'
        assert data['id'] == 'doc'
        assert data['kind'] == 'dashboard'
        assert data['version'] == 1
        assert data['display_name'] is None
        self.assert_no_personal(response)

    def test_shared_display_name_from_profile_only(self):
        self.create()
        token = self.token()
        DocumentProfile.objects.create(user=self.alice, display_name='')
        assert self.shared(token).json()['data']['display_name'] is None
        DocumentProfile.objects.filter(user=self.alice).update(display_name='Air Fan')
        assert self.shared(token).json()['data']['display_name'] == 'Air Fan'

    def test_shared_works_signed_out(self):
        self.create()
        token = self.token()
        response = self.shared(token, client=Client())
        assert response.status_code == 200
        assert response.json()['data']['body'] == {'widgets': []}
        bob = Client()
        bob.force_login(self.bob)
        assert self.shared(token, client=bob).status_code == 200

    def test_shared_changes_unchanged(self):
        self.create()
        token = self.token()
        response = self.shared_changes(token, since=1)
        assert response.status_code == 200
        assert response['Cache-Control'] == 'no-store'
        assert response.json() == {'data': {'version': 1}}

        self.create(base_version=1, name='Renamed')
        changed = self.shared_changes(token, since=1)
        assert changed.status_code == 200
        data = changed.json()['data']
        assert set(data) == SHARED_KEYS
        assert data['id'] == 'doc'
        assert data['version'] == 2
        assert data['name'] == 'Renamed'
        self.assert_no_personal(changed)

    def test_shared_changes_bad_since(self):
        self.create()
        token = self.token()
        for params in ({}, {'since': 'x'}, {'since': '-1'}):
            with self.subTest(params=params):
                response = self.shared_changes(token, **params)
                assert response.status_code == 400
                assert response.json()['errors']['detail'][0]['code'] == 'invalid'
                # A bad since on an unknown token does not reveal that it is unknown or known.
                self.assert_unavailable(self.shared_changes('tok-unknown-0000000000', **params))

    def test_credit_owner_or_shared_only(self):
        self.create(name='Mine')
        bob = Client()
        bob.force_login(self.bob)
        missing = self.credit('nope', client=bob)
        self.assert_unavailable(missing)

        owner = self.credit(client=self.client)
        assert owner.status_code == 200
        assert owner.json() == {'data': {'name': 'Mine', 'display_name': None}}

        private = self.credit(client=bob)
        self.assert_unavailable(private)
        assert private.content == missing.content
        assert self.credit().content == missing.content

        self.token()
        DocumentProfile.objects.create(user=self.alice, display_name='Air Fan')
        for client in (bob, self.anon):
            response = self.credit(client=client)
            assert response.status_code == 200
            assert response['Cache-Control'] == 'no-store'
            assert response.json() == {'data': {'name': 'Mine', 'display_name': 'Air Fan'}}
            self.assert_no_personal(response)

        self.revoke()
        assert self.credit(client=bob).content == missing.content

    def test_profile_display_name_round_trip_and_blank_is_null(self):
        url = f'{BASE}profile/'
        response = self.client.get(url)
        assert response.status_code == 200
        assert response['Cache-Control'] == 'no-store'
        assert response.json() == {'data': {'display_name': None}}
        # Reading never creates a profile; only a PUT does.
        assert not DocumentProfile.objects.filter(user=self.alice).exists()

        def put(value):
            return self.client.put(
                url, json.dumps({'display_name': value}), content_type='application/json'
            )

        response = put('  Air Fan  ')
        assert response.status_code == 200
        assert response.json() == {'data': {'display_name': 'Air Fan'}}
        assert self.client.get(url).json() == {'data': {'display_name': 'Air Fan'}}
        assert DocumentProfile.objects.get(user=self.alice).display_name == 'Air Fan'

        assert put('   ').json() == {'data': {'display_name': None}}
        assert DocumentProfile.objects.get(user=self.alice).display_name is None
        put('Air Fan')
        assert put(None).json() == {'data': {'display_name': None}}

        assert put('x' * 60).status_code == 200
        for bad in ('x' * 61, 5, ['a']):
            with self.subTest(bad=bad):
                response = put(bad)
                assert response.status_code == 400
                payload = response.json()
                assert payload['errors']['detail'][0]['code'] == 'invalid'
                assert 'display_name' in payload['data']['fields']
        assert self.anon.get(url).status_code == 401

    def test_profile_is_a_fixed_route(self):
        # profile/ is routed before <id>/: a document save sent there is a bad profile PUT,
        # and it leaves the display name alone.
        DocumentProfile.objects.create(user=self.alice, display_name='Air Fan')
        response = save(self.client, 'profile')
        assert response.status_code == 400
        assert 'display_name' in response.json()['data']['fields']
        assert not SavedDocument.objects.filter(pk='profile').exists()
        assert DocumentProfile.objects.get(user=self.alice).display_name == 'Air Fan'

    def test_share_blocked_owner_refused(self):
        self.create()
        DocumentProfile.objects.create(user=self.alice, sharing_blocked=True)
        response = self.share()
        assert response.status_code == 403
        assert response.json()['errors']['detail'][0]['code'] == 'sharing_blocked'
        assert SavedDocument.objects.get(pk='doc').share_token is None

    def test_share_disabled_doc_refused(self):
        self.create()
        SavedDocument.objects.filter(pk='doc').update(sharing_disabled=True)
        response = self.share()
        assert response.status_code == 403
        assert response.json()['errors']['detail'][0]['code'] == 'sharing_blocked'
