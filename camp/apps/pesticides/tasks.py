from django_huey import db_periodic_task, get_queue
from huey import crontab


@db_periodic_task(crontab(minute='0', hour='14'), priority=50)
def fetch_pesticide_notices():
    from camp.apps.pesticides.spraydays import fetch_applications
    with get_queue('primary').lock_task('fetch-pesticide-notices'):
        fetch_applications()
