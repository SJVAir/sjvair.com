from unittest.mock import patch

from django.test import TestCase

from camp.apps.emissions import tasks


class ImportIcisAirTaskTests(TestCase):
    @patch('camp.apps.emissions.tasks.call_command')
    def test_runs_the_command_under_the_lock(self, call_command):
        tasks.import_icis_air.call_local()
        call_command.assert_called_once_with('import_icis_air')

    def test_schedule(self):
        # Weekly, Mondays at 12:00 UTC: the day after ECHO's weekly refresh.
        from datetime import datetime
        task_class = tasks.import_icis_air.task_class
        assert task_class.validate_datetime(task_class, datetime(2026, 10, 5, 12, 0))  # a Monday
        assert task_class.validate_datetime(task_class, datetime(2026, 10, 12, 12, 0))
        assert not task_class.validate_datetime(task_class, datetime(2026, 10, 6, 12, 0))  # Tuesday
        assert not task_class.validate_datetime(task_class, datetime(2026, 10, 5, 11, 0))


class ImportWellsTaskTests(TestCase):
    @patch('camp.apps.emissions.tasks.call_command')
    def test_runs_the_command_under_the_lock(self, call_command):
        tasks.import_wells.call_local()
        call_command.assert_called_once_with('import_wells')

    def test_schedule(self):
        # Weekly, Sundays at 12:00 UTC: doesn't collide with the Monday ICIS task.
        from datetime import datetime
        task_class = tasks.import_wells.task_class
        assert task_class.validate_datetime(task_class, datetime(2026, 10, 4, 12, 0))  # a Sunday
        assert task_class.validate_datetime(task_class, datetime(2026, 10, 11, 12, 0))
        assert not task_class.validate_datetime(task_class, datetime(2026, 10, 5, 12, 0))  # Monday
        assert not task_class.validate_datetime(task_class, datetime(2026, 10, 4, 11, 0))


class ImportCarbonMapperTaskTests(TestCase):
    @patch('camp.apps.emissions.tasks.call_command')
    def test_runs_the_command_under_the_lock(self, call_command):
        tasks.import_carbon_mapper.call_local()
        call_command.assert_called_once_with('import_carbon_mapper')
