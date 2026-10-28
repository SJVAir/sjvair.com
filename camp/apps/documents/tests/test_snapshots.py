from datetime import datetime, timedelta
from unittest import mock
from zoneinfo import ZoneInfo

from django.core.cache import cache
from django.test import Client, TestCase, override_settings

from camp.api.v2.documents.tests.helpers import body, make_user, save
from camp.apps.documents import snapshots
from camp.apps.documents.models import DocumentSnapshot, SavedDocument, measure

PACIFIC = ZoneInfo('America/Los_Angeles')


class SnapshotTests(TestCase):
    def setUp(self):
        cache.clear()
        self.alice = make_user(1)
        self.client = Client()
        self.client.force_login(self.alice)

    def put(self, id='doc', **overrides):
        response = save(self.client, id, **overrides)
        self.assertEqual(response.status_code, 200, response.content)

    def test_create_takes_no_snapshot(self):
        self.put(body=body(1))
        self.assertFalse(DocumentSnapshot.objects.exists())

    def test_first_save_of_day_snapshots_stored_version(self):
        self.put(body=body(1), name='Old')
        self.put(base_version=1, body=body(2), name='New')
        snap = DocumentSnapshot.objects.get()
        self.assertEqual(snap.reason, 'daily')
        self.assertEqual(snap.version, 1)
        self.assertEqual(snap.name, 'Old')
        self.assertEqual(snap.body, body(1))
        self.assertEqual(snap.size, measure(body(1)))
        self.assertEqual(snap.owner, self.alice)

    def test_second_save_same_day_no_snapshot(self):
        self.put()
        self.put(base_version=1)
        self.put(base_version=2)
        self.assertEqual(DocumentSnapshot.objects.count(), 1)

    def test_next_pacific_day_snapshots_again(self):
        self.put()
        self.put(base_version=1)
        # 23:30 Pacific on the snapshot's day is still that day; 00:30 next day is a new one.
        taken = DocumentSnapshot.objects.get().created_at.astimezone(PACIFIC)
        midnight = datetime.combine(taken.date(), datetime.min.time(), tzinfo=PACIFIC)
        late = midnight + timedelta(hours=23, minutes=30)
        with mock.patch('django.utils.timezone.now', return_value=late):
            self.put(base_version=2)
        self.assertEqual(DocumentSnapshot.objects.count(), 1)
        with mock.patch('django.utils.timezone.now', return_value=midnight + timedelta(hours=24, minutes=30)):
            self.put(base_version=3)
        self.assertEqual(DocumentSnapshot.objects.count(), 2)

    def test_schema_bump_snapshots(self):
        self.put()
        self.put(base_version=1)  # daily
        self.put(base_version=2, schema_version=2)
        latest = DocumentSnapshot.objects.order_by('-pk').first()
        self.assertEqual(latest.reason, 'schema')
        self.assertEqual(latest.schema_version, 1)
        self.assertEqual(DocumentSnapshot.objects.count(), 2)

    def test_conflict_flag_snapshots_even_same_day(self):
        self.put()
        self.put(base_version=1)  # daily
        self.put(base_version=2, snapshot='conflict')
        self.assertEqual(
            list(DocumentSnapshot.objects.order_by('pk').values_list('reason', flat=True)),
            ['daily', 'conflict'],
        )

    def test_one_snapshot_per_save_by_priority(self):
        self.put()
        self.put(base_version=1, schema_version=2, snapshot='conflict')
        self.assertEqual(DocumentSnapshot.objects.get().reason, 'schema')

    def test_snapshot_cap_trims_oldest_never_refuses(self):
        size = measure(body(1))
        with override_settings(DOCUMENTS_MAX_SNAPSHOT_STORAGE=size * 2):
            self.put(body=body(1))
            for base in (1, 2, 3):
                self.put(base_version=base, body=body(1), snapshot='conflict')
            self.assertEqual(SavedDocument.objects.get().version, 4)
            versions = list(DocumentSnapshot.objects.order_by('pk').values_list('version', flat=True))
            self.assertEqual(versions, [2, 3])
            self.assertLessEqual(sum(DocumentSnapshot.objects.values_list('size', flat=True)), size * 2)

    def test_start_of_day_is_pacific(self):
        now = datetime(2026, 10, 28, 3, 0, tzinfo=ZoneInfo('UTC'))  # Oct 27, 20:00 Pacific
        self.assertEqual(snapshots.start_of_day(now), datetime(2026, 10, 27, tzinfo=PACIFIC))
