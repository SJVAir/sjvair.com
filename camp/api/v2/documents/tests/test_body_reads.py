from django.db import connection
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext

from camp.apps.documents.models import DocumentSnapshot

from .helpers import BASE, body_queries, make_user, save


def document_body_reads(captured):
    """The captured queries that read a SavedDocument's body (a snapshot's is its own table)."""
    return [sql for sql in body_queries(captured) if '"documents_saveddocument"."body"' in sql]


class BodyReadTests(TestCase):
    """Endpoints that answer from a document's metadata never read its body (up to 1 MB)."""

    def setUp(self):
        self.alice = make_user(1)
        self.client = Client()
        self.client.force_login(self.alice)
        assert save(self.client, 'doc').status_code == 200
        self.anon = Client()

    def reads(self, request):
        with CaptureQueriesContext(connection) as captured:
            response = request()
        return response, document_body_reads(captured)

    def share(self):
        response = self.client.post(f'{BASE}doc/share/')
        assert response.status_code == 200
        return response.json()['data']['share_token']

    def test_unchanged_poll_skips_body(self):
        response, reads = self.reads(lambda: self.client.get(f'{BASE}doc/changes/', {'since': 1}))
        assert response.json() == {'data': {'version': 1}}
        assert reads == []

    def test_changed_poll_reads_body_with_version(self):
        assert save(self.client, 'doc', base_version=1).status_code == 200
        response, reads = self.reads(lambda: self.client.get(f'{BASE}doc/changes/', {'since': 1}))
        data = response.json()['data']
        assert data['version'] == data['document']['version'] == 2
        assert 'body' in data['document']
        assert len(reads) == 1

    def test_unchanged_shared_poll_skips_body(self):
        token = self.share()
        response, reads = self.reads(
            lambda: self.anon.get(f'{BASE}shared/{token}/changes/', {'since': 1}))
        assert response.json() == {'data': {'version': 1}}
        assert reads == []

    def test_changed_shared_poll_reads_body(self):
        token = self.share()
        assert save(self.client, 'doc', base_version=1).status_code == 200
        response, reads = self.reads(
            lambda: self.anon.get(f'{BASE}shared/{token}/changes/', {'since': 1}))
        assert response.json()['data']['version'] == 2
        assert 'body' in response.json()['data']
        assert len(reads) == 1

    def test_share_and_revoke_skip_body(self):
        response, reads = self.reads(lambda: self.client.post(f'{BASE}doc/share/'))
        assert response.status_code == 200
        assert reads == []
        response, reads = self.reads(lambda: self.client.delete(f'{BASE}doc/share/'))
        assert response.status_code == 204
        assert reads == []

    def test_snapshot_detail_skips_document_body(self):
        snap = DocumentSnapshot.objects.create(
            document_id='doc', owner=self.alice, version=1, schema_version=1, name='v1',
            body={'v': 1}, size=9, reason='daily',
        )
        response, reads = self.reads(lambda: self.client.get(f'{BASE}doc/snapshots/{snap.sqid}/'))
        assert response.json()['data']['body'] == {'v': 1}
        assert reads == []

    def test_credit_skips_body(self):
        self.share()
        response, reads = self.reads(lambda: self.anon.get(f'{BASE}doc/credit/'))
        assert response.status_code == 200
        assert reads == []
