from django_huey import db_periodic_task, task
from huey import crontab
from .views import CachedEndpointMixin


@task()
def add(x, y):
    '''
        A task used for testing the queue.
    '''
    return x + y


@db_periodic_task(crontab(minute='*'), priority=100)
def refresh_cached_endpoints():
    results = CachedEndpointMixin.prewarm_all_registered()
    for view_cls, status in results:
        if status != 200:
            pass
