from django.core.management import call_command
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


@db_periodic_task(crontab(minute=10))
def silky_garbage_collection():
    '''
    Garbage collect silky as a background task outside the request/response cycle
    https://github.com/jazzband/django-silk#limiting-requestresponse-data
    '''
    call_command('silk_request_garbage_collect')
