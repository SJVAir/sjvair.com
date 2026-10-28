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
        self.assertEqual(response.status_code, 200)
        return response

    def share(self, id='doc', client=None):
        return (client or self.client).post(f'{BASE}{id}/share/')

    def revoke(self, id='doc', client=None):
        return (client or self.client).delete(f'{BASE}{id}/share/')

    def token(self, id='doc'):
        response = self.share(id)
        self.assertEqual(response.status_code, 200)
        return response.json()['data']['share_token']

    def shared(self, token, client=None):
        return (client or self.anon).get(f'{BASE}shared/{token}/')

    def shared_changes(self, token, **params):
        return self.anon.get(f'{BASE}shared/{token}/changes/', params)

    def credit(self, id='doc', client=None):
        return (client or self.anon).get(f'{BASE}{id}/credit/')

    def assert_unavailable(self, response):
        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.json()['errors']['detail'][0]['code'], 'not_found')
        self.assertEqual(response['Cache-Control'], 'no-store')

    def test_share_creates_token_of_22_plus_chars(self):
        self.create()
        response = self.share()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Cache-Control'], 'no-store')
        token = response.json()['data']['share_token']
        self.assertGreaterEqual(len(token), 22)
        doc = SavedDocument.objects.get(pk='doc')
        self.assertEqual(doc.share_token, token)
        self.assertEqual(doc.visibility, 'link')

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
        self.assertNotIn('doc', self.listed_since(cursor))

        token = self.token()
        listed = self.listed_since(cursor)['doc']
        self.assertEqual((listed['visibility'], listed['share_token']), ('link', token))
        self.assertEqual(listed['version'], 1)

        self.age()
        self.assertEqual(self.revoke().status_code, 204)
        listed = self.listed_since(cursor)['doc']
        self.assertEqual((listed['visibility'], listed['share_token']), ('private', None))
        self.assertEqual(listed['version'], 1)

    def test_share_twice_same_token(self):
        self.create()
        self.assertEqual(self.token(), self.token())

    def test_share_others_or_missing_is_not_found(self):
        self.create()
        bob = Client()
        bob.force_login(self.bob)
        theirs = self.share(client=bob)
        missing = self.share('nope')
        self.assert_unavailable(theirs)
        self.assertEqual(theirs.content, missing.content)
        self.assert_unavailable(self.revoke(client=bob))
        self.assertIsNone(SavedDocument.objects.get(pk='doc').share_token)

    def test_share_deleted_is_not_found(self):
        self.create(deleted_at='2026-10-28T00:00:00Z')
        self.assert_unavailable(self.share())

    def test_share_requires_login(self):
        self.create()
        self.assertEqual(self.share(client=self.anon).status_code, 401)
        self.assertEqual(self.revoke(client=self.anon).status_code, 401)

    def test_revoke_then_share_new_token_old_dead(self):
        self.create()
        old = self.token()
        self.assertEqual(self.shared(old).status_code, 200)

        response = self.revoke()
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response['Cache-Control'], 'no-store')
        doc = SavedDocument.objects.get(pk='doc')
        self.assertIsNone(doc.share_token)
        self.assertEqual(doc.visibility, 'private')
        self.assert_unavailable(self.shared(old))

        new = self.token()
        self.assertNotEqual(new, old)
        self.assertEqual(self.shared(new).status_code, 200)
        self.assert_unavailable(self.shared(old))
        self.assert_unavailable(self.shared_changes(old, since=0))

    def test_soft_delete_hides_then_restore_same_link(self):
        self.create()
        token = self.token()
        self.create(base_version=1, deleted_at='2026-10-28T00:00:00Z')
        unknown = self.shared('no-such-token-at-all-xx')
        hidden = self.shared(token)
        self.assert_unavailable(hidden)
        self.assertEqual(hidden.content, unknown.content)

        self.create(base_version=2, deleted_at=None)
        restored = self.shared(token)
        self.assertEqual(restored.status_code, 200)
        self.assertEqual(restored.json()['data']['version'], 3)
        self.assertEqual(SavedDocument.objects.get(pk='doc').share_token, token)

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
                    self.assertEqual(response.status_code, first.status_code)
                    self.assertEqual(response.content, first.content)
        self.assertEqual(reads['unknown'].content, polls['unknown'].content)
        self.assertIn(b'This shared dashboard is no longer available.', reads['unknown'].content)

    def token_for(self, client, id):
        response = self.share(id, client=client)
        self.assertEqual(response.status_code, 200)
        return response.json()['data']['share_token']

    def assert_no_personal(self, response):
        content = response.content.decode()
        for value in (self.alice.email, self.alice.full_name, str(self.alice.phone)):
            self.assertNotIn(value, content)
        data = response.json()['data']
        self.assertNotIn('owner', data)
        self.assertNotIn('owner_id', data)
        self.assertNotIn(f'"{self.alice.pk}"', content)

    def test_shared_has_no_personal_fields(self):
        self.create(name='Fresno air')
        token = self.token()
        response = self.shared(token)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Cache-Control'], 'no-store')
        data = response.json()['data']
        self.assertEqual(set(data), SHARED_KEYS)
        self.assertEqual(data['name'], 'Fresno air')
        self.assertEqual(data['id'], 'doc')
        self.assertEqual(data['kind'], 'dashboard')
        self.assertEqual(data['version'], 1)
        self.assertIsNone(data['display_name'])
        self.assert_no_personal(response)

    def test_shared_display_name_from_profile_only(self):
        self.create()
        token = self.token()
        DocumentProfile.objects.create(user=self.alice, display_name='')
        self.assertIsNone(self.shared(token).json()['data']['display_name'])
        DocumentProfile.objects.filter(user=self.alice).update(display_name='Air Fan')
        self.assertEqual(self.shared(token).json()['data']['display_name'], 'Air Fan')

    def test_shared_works_signed_out(self):
        self.create()
        token = self.token()
        response = self.shared(token, client=Client())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['data']['body'], {'widgets': []})
        bob = Client()
        bob.force_login(self.bob)
        self.assertEqual(self.shared(token, client=bob).status_code, 200)

    def test_shared_changes_unchanged(self):
        self.create()
        token = self.token()
        response = self.shared_changes(token, since=1)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Cache-Control'], 'no-store')
        self.assertEqual(response.json(), {'data': {'version': 1}})

        self.create(base_version=1, name='Renamed')
        changed = self.shared_changes(token, since=1)
        self.assertEqual(changed.status_code, 200)
        data = changed.json()['data']
        self.assertEqual(set(data), SHARED_KEYS)
        self.assertEqual(data['id'], 'doc')
        self.assertEqual(data['version'], 2)
        self.assertEqual(data['name'], 'Renamed')
        self.assert_no_personal(changed)

    def test_shared_changes_bad_since(self):
        self.create()
        token = self.token()
        for params in ({}, {'since': 'x'}, {'since': '-1'}):
            with self.subTest(params=params):
                response = self.shared_changes(token, **params)
                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()['errors']['detail'][0]['code'], 'invalid')
                # A bad since on an unknown token does not reveal that it is unknown or known.
                self.assert_unavailable(self.shared_changes('tok-unknown-0000000000', **params))

    def test_credit_owner_or_shared_only(self):
        self.create(name='Mine')
        bob = Client()
        bob.force_login(self.bob)
        missing = self.credit('nope', client=bob)
        self.assert_unavailable(missing)

        owner = self.credit(client=self.client)
        self.assertEqual(owner.status_code, 200)
        self.assertEqual(owner.json(), {'data': {'name': 'Mine', 'display_name': None}})

        private = self.credit(client=bob)
        self.assert_unavailable(private)
        self.assertEqual(private.content, missing.content)
        self.assertEqual(self.credit().content, missing.content)

        self.token()
        DocumentProfile.objects.create(user=self.alice, display_name='Air Fan')
        for client in (bob, self.anon):
            response = self.credit(client=client)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response['Cache-Control'], 'no-store')
            self.assertEqual(response.json(), {'data': {'name': 'Mine', 'display_name': 'Air Fan'}})
            self.assert_no_personal(response)

        self.revoke()
        self.assertEqual(self.credit(client=bob).content, missing.content)

    def test_profile_display_name_round_trip_and_blank_is_null(self):
        url = f'{BASE}profile/'
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Cache-Control'], 'no-store')
        self.assertEqual(response.json(), {'data': {'display_name': None}})

        def put(value):
            return self.client.put(
                url, json.dumps({'display_name': value}), content_type='application/json'
            )

        response = put('  Air Fan  ')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'data': {'display_name': 'Air Fan'}})
        self.assertEqual(self.client.get(url).json(), {'data': {'display_name': 'Air Fan'}})
        self.assertEqual(DocumentProfile.objects.get(user=self.alice).display_name, 'Air Fan')

        self.assertEqual(put('   ').json(), {'data': {'display_name': None}})
        self.assertIsNone(DocumentProfile.objects.get(user=self.alice).display_name)
        put('Air Fan')
        self.assertEqual(put(None).json(), {'data': {'display_name': None}})

        self.assertEqual(put('x' * 60).status_code, 200)
        for bad in ('x' * 61, 5, ['a']):
            with self.subTest(bad=bad):
                response = put(bad)
                self.assertEqual(response.status_code, 400)
                payload = response.json()
                self.assertEqual(payload['errors']['detail'][0]['code'], 'invalid')
                self.assertIn('display_name', payload['data']['fields'])
        self.assertEqual(self.anon.get(url).status_code, 401)

    def test_profile_is_a_fixed_route(self):
        # profile/ is routed before <id>/: a document save sent there is a bad profile PUT,
        # and it leaves the display name alone.
        DocumentProfile.objects.create(user=self.alice, display_name='Air Fan')
        response = save(self.client, 'profile')
        self.assertEqual(response.status_code, 400)
        self.assertIn('display_name', response.json()['data']['fields'])
        self.assertFalse(SavedDocument.objects.filter(pk='profile').exists())
        self.assertEqual(DocumentProfile.objects.get(user=self.alice).display_name, 'Air Fan')

    def test_share_blocked_owner_refused(self):
        self.create()
        DocumentProfile.objects.create(user=self.alice, sharing_blocked=True)
        response = self.share()
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()['errors']['detail'][0]['code'], 'sharing_blocked')
        self.assertIsNone(SavedDocument.objects.get(pk='doc').share_token)

    def test_share_disabled_doc_refused(self):
        self.create()
        SavedDocument.objects.filter(pk='doc').update(sharing_disabled=True)
        response = self.share()
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()['errors']['detail'][0]['code'], 'sharing_blocked')
