import peewee
from django.test import TestCase
from huey import MemoryHuey
from huey.contrib.djhuey.stats import admin as stats_admin

from camp.apps.queues.stats import configure_queue_stats


class ConfigureQueueStatsTests(TestCase):
    def setUp(self):
        # Restore the dashboard's queue resolver after each test so the
        # monkeypatch never leaks between tests.
        original = stats_admin.get_huey
        self.original_get_huey = original
        self.addCleanup(setattr, stats_admin, 'get_huey', original)

    def test_wires_recorder_and_dashboard_for_live_queue(self):
        queue = MemoryHuey('test-live', immediate=False)
        db = peewee.SqliteDatabase(':memory:')

        result = configure_queue_stats('ignored', queue=queue, db=db)

        assert result is queue
        assert getattr(queue, '_stats', None) is not None
        assert stats_admin.get_huey() is queue

    def test_noop_when_queue_is_immediate(self):
        queue = MemoryHuey('test-immediate', immediate=True)
        db = peewee.SqliteDatabase(':memory:')

        result = configure_queue_stats('ignored', queue=queue, db=db)

        assert result is None
        assert getattr(queue, '_stats', None) is None
        assert stats_admin.get_huey is self.original_get_huey

    def test_swallows_errors_and_leaves_dashboard_untouched(self):
        from unittest import mock

        queue = MemoryHuey('test-error', immediate=False)
        db = peewee.SqliteDatabase(':memory:')

        with mock.patch('huey.contrib.stats.enable_stats', side_effect=RuntimeError('boom')):
            result = configure_queue_stats('ignored', queue=queue, db=db)

        assert result is None
        assert stats_admin.get_huey is self.original_get_huey
