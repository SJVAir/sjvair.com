import json
from datetime import datetime
from unittest import mock
from zoneinfo import ZoneInfo

from django.test import Client, TestCase
from django.utils import timezone

from camp.apps.documents.models import SavedDocument

from .helpers import BASE, make_user


def seed(owner, id, **extra):
    fields = dict(
        id=id, owner=owner, kind='dashboard', name=id, body={'a': 1}, size=7, schema_version=1,
        version=3,
    )
    fields.update(extra)
    return SavedDocument.objects.create(**fields)


class ExportTests(TestCase):
    def setUp(self):
        self.alice = make_user(1)
        self.bob = make_user(2)
        self.client = Client()
        self.client.force_login(self.alice)

    def test_signed_out_401(self):
        self.assertEqual(Client().get(f'{BASE}export/').status_code, 401)

    def test_export_envelope_shape(self):
        seed(self.alice, 'a', name='Alpha')
        seed(self.alice, 'b', name=None, copied_from='a')
        seed(self.alice, 'gone', deleted_at=timezone.now())
        seed(self.bob, 'theirs')
        # 05:30 UTC on the 29th is still the 28th in Pacific time.
        now = datetime(2026, 10, 29, 5, 30, 15, 123456, tzinfo=ZoneInfo('UTC'))
        with mock.patch('camp.api.v2.documents.endpoints.timezone.now', return_value=now):
            response = self.client.get(f'{BASE}export/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Cache-Control'], 'no-store')
        self.assertEqual(
            response['Content-Disposition'],
            'attachment; filename="sjvair-dashboards-2026-10-28.json"',
        )
        data = json.loads(response.content)
        self.assertEqual(
            set(data), {'format', 'type', 'formatVersion', 'exportedAt', 'documents'}
        )
        self.assertEqual(data['format'], 'sjvair-workspace')
        self.assertEqual(data['type'], 'backup')
        self.assertEqual(data['formatVersion'], 1)
        self.assertEqual(data['exportedAt'], '2026-10-29T05:30:15.123Z')
        docs = {d['id']: d for d in data['documents']}
        self.assertEqual(set(docs), {'a', 'b'})
        self.assertEqual(
            set(docs['a']),
            {'kind', 'schemaVersion', 'id', 'name', 'version', 'createdAt', 'updatedAt', 'body'},
        )
        self.assertNotIn('copiedFrom', docs['a'])
        self.assertEqual(docs['b']['copiedFrom'], 'a')
        self.assertIsNone(docs['b']['name'])
        self.assertEqual(docs['a']['version'], 0)
        self.assertEqual(docs['a']['body'], {'a': 1})
        self.assertEqual(docs['a']['schemaVersion'], 1)
        self.assertRegex(docs['a']['createdAt'], r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$')
        self.assertRegex(docs['a']['updatedAt'], r'^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$')

    def test_export_empty(self):
        data = json.loads(self.client.get(f'{BASE}export/').content)
        self.assertEqual(data['documents'], [])
