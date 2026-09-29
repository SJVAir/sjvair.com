from unittest.mock import patch

from django.test import TestCase

from camp.apps.emissions import tasks


class ImportIcisAirTaskTests(TestCase):
    @patch('camp.apps.emissions.tasks.call_command')
    def test_runs_the_command_under_the_lock(self, call_command):
        tasks.import_icis_air.call_local()
        call_command.assert_called_once_with('import_icis_air')

    def test_schedule(self):
        # Monthly, the 2nd at 11:00 UTC: ECHO refreshes weekly, the district's feed monthly at best.
        from datetime import datetime
        task_class = tasks.import_icis_air.task_class
        assert task_class.validate_datetime(task_class, datetime(2026, 10, 2, 11, 0))
        assert not task_class.validate_datetime(task_class, datetime(2026, 10, 3, 11, 0))
        assert not task_class.validate_datetime(task_class, datetime(2026, 10, 2, 12, 0))
