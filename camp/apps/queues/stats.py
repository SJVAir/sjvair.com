import logging

logger = logging.getLogger('huey')


def configure_queue_stats(queue_name, queue=None, db=None):
    """Attach huey's stats recorder to a django-huey queue and point the
    built-in dashboard admin at that same instance.

    Idempotent per huey instance (``enable_stats`` no-ops if already attached).
    Returns the wired queue, or ``None`` when the queue runs in immediate mode
    (tests / local DEBUG), where there is no consumer to monitor. Any failure
    (e.g. huey internals moving on a future upgrade) is logged and swallowed so
    a broken dashboard never stops a process from starting.
    """
    try:
        from django_huey import get_queue
        from huey.contrib.stats import enable_stats
        from huey.contrib.djhuey.stats import admin as stats_admin
        from huey.contrib.djhuey.stats.apps import stats_database

        if queue is None:
            queue = get_queue(queue_name)

        if queue.immediate:
            return None

        if db is None:
            db, options = stats_database()
        else:
            options = {}

        enable_stats(queue, db, **options)
        stats_admin.get_huey = lambda: queue
        return queue
    except Exception:
        logger.exception('Failed to wire huey stats dashboard for queue %r', queue_name)
        return None
