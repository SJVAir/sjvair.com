from huey import PriorityRedisHuey as BasePriorityRedisHuey


class InFlightTasks(set):
    """
    huey 3.3.0 tracks running tasks in `Huey._tasks_in_flight` and, when the
    consumer stops, `notify_interrupted_tasks()` pops every entry (to emit
    SIGNAL_INTERRUPTED) while worker threads are still running. A worker that
    then finishes its task calls `_tasks_in_flight.remove(task)` in `_execute`'s
    `finally`, raising KeyError, which huey logs as "Unhandled exception in
    task" and which skips the task's result handling. Make removal idempotent.
    """

    def remove(self, item):
        self.discard(item)


class TolerantInFlightMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._tasks_in_flight = InFlightTasks(self._tasks_in_flight)


class PriorityRedisHuey(TolerantInFlightMixin, BasePriorityRedisHuey):
    pass
