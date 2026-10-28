from datetime import timedelta

from django.db import connection
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from camp.apps.documents.models import DocumentSnapshot, SavedDocument

from .helpers import BASE, body_queries, make_user


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
