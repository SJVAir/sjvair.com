from django.test import Client, TestCase

from camp.apps.documents.models import DocumentChange, PurgedDocument

from .helpers import BASE, make_user, save


def change(n):
    return {'schema_version': 1, 'change': {'op': 'set', 'n': n}}


class ChangesTests(TestCase):
    def setUp(self):
        self.alice = make_user(1)
        self.bob = make_user(2)
        self.client = Client()
        self.client.force_login(self.alice)

    def save_versions(self, id, count):
        """Create `id` and save it up to version `count`, one change per version."""
        for v in range(1, count + 1):
            response = save(
                self.client, id, base_version=None if v == 1 else v - 1, changes=[change(v)]
            )
            self.assertEqual(response.status_code, 200)

    def poll(self, id, **params):
        return self.client.get(f'{BASE}{id}/changes/', params)

    def test_unchanged_is_version_only(self):
        self.save_versions('doc', 3)
        response = self.poll('doc', since=3)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'data': {'version': 3}})
        self.assertEqual(response['Cache-Control'], 'no-store')

    def test_changes_in_order(self):
        self.save_versions('doc', 4)
        data = self.poll('doc', since=1).json()['data']
        self.assertEqual(data['version'], 4)
        self.assertEqual(
            data['changes'],
            [{'version': v, 'schema_version': 1, 'change': change(v)['change']} for v in (2, 3, 4)],
        )
        self.assertEqual(data['document']['id'], 'doc')
        self.assertEqual(data['document']['version'], 4)
        self.assertIn('body', data['document'])

    def test_matches_stale_base_changes(self):
        self.save_versions('doc', 3)
        stale = save(self.client, 'doc', base_version=1).json()['data']
        polled = self.poll('doc', since=1).json()['data']
        self.assertEqual(polled['changes'], stale['changes'])

    def test_gap_is_null(self):
        self.save_versions('doc', 4)
        DocumentChange.objects.filter(document_id='doc', version=3).delete()
        data = self.poll('doc', since=1).json()['data']
        self.assertEqual(data['version'], 4)
        self.assertIsNone(data['changes'])
        self.assertEqual(data['document']['version'], 4)

    def test_client_ahead_is_null_with_document(self):
        self.save_versions('doc', 2)
        response = self.poll('doc', since=9)
        self.assertEqual(response.status_code, 200)
        data = response.json()['data']
        self.assertEqual(data['version'], 2)
        self.assertIsNone(data['changes'])
        self.assertEqual(data['document']['id'], 'doc')

    def test_since_zero_returns_all(self):
        self.save_versions('doc', 2)
        data = self.poll('doc', since=0).json()['data']
        self.assertEqual([e['version'] for e in data['changes']], [1, 2])

    def test_bad_since_is_invalid(self):
        self.save_versions('doc', 1)
        for params in ({}, {'since': 'x'}, {'since': '-1'}, {'since': '1.5'}, {'since': ''}):
            response = self.poll('doc', **params)
            self.assertEqual(response.status_code, 400, params)
            body = response.json()
            self.assertEqual(body['errors']['detail'][0]['code'], 'invalid')
            self.assertIn('since', body['data']['fields'])

    def test_other_owner_not_found(self):
        self.save_versions('doc', 2)
        other = Client()
        other.force_login(self.bob)
        theirs = other.get(f'{BASE}doc/changes/', {'since': 1})
        missing = other.get(f'{BASE}nope/changes/', {'since': 1})
        self.assertEqual(theirs.status_code, 404)
        self.assertEqual(theirs.content, missing.content)
        self.assertEqual(theirs['Cache-Control'], 'no-store')

    def test_purged_gone(self):
        PurgedDocument.objects.create(id='old', owner=self.alice)
        response = self.poll('old', since=1)
        self.assertEqual(response.status_code, 410)
        self.assertEqual(response.json()['errors']['detail'][0]['code'], 'gone')

    def test_signed_out_401(self):
        self.assertEqual(Client().get(f'{BASE}doc/changes/', {'since': 1}).status_code, 401)
