import logging

import pytest
from django.test import SimpleTestCase
from huey import MemoryHuey

from camp.utils.huey import PriorityRedisHuey, TolerantInFlightMixin


class TolerantMemoryHuey(TolerantInFlightMixin, MemoryHuey):
    pass


class InFlightTasksTests(SimpleTestCase):
    def make_huey(self, cls):
        # Not immediate: immediate mode bypasses Huey._execute and the in-flight set.
        return cls('test-inflight', immediate=False)

    def run_task_interrupted_mid_flight(self, huey):
        @huey.task()
        def job():
            # Consumer shutdown during the task: pops everything in flight.
            huey.notify_interrupted_tasks()
            return 'done'

        task = job.s()
        return huey.execute(task)

    def test_stock_huey_logs_keyerror_when_interrupted_mid_task(self):
        # Documents the upstream behavior this project works around.
        with self.assertLogs('huey', level=logging.ERROR) as logs:
            self.run_task_interrupted_mid_flight(self.make_huey(MemoryHuey))
        assert 'Unhandled exception in task' in logs.output[0]
        assert 'KeyError' in logs.output[0]

    def test_tolerant_huey_survives_interruption_mid_task(self):
        huey = self.make_huey(TolerantMemoryHuey)
        with self.assertNoLogs('huey', level=logging.ERROR):
            self.run_task_interrupted_mid_flight(huey)
        assert len(huey._tasks_in_flight) == 0

    def test_project_class_uses_tolerant_set(self):
        assert issubclass(PriorityRedisHuey, TolerantInFlightMixin)
