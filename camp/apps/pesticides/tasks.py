from django_huey import db_periodic_task, db_task, get_queue
from huey import crontab


@db_periodic_task(crontab(minute='0', hour='14'), priority=50)
def fetch_pesticide_notices():
    from camp.apps.pesticides.spraydays import fetch_applications
    with get_queue('primary').lock_task('fetch-pesticide-notices'):
        fetch_applications()


@db_periodic_task(crontab(minute='15', hour='*/6'), priority=20)
def refresh_pesticide_landing_stats():
    from camp.apps.pesticides.stats import refresh_landing_stats
    with get_queue('primary').lock_task('refresh-pesticide-landing-stats'):
        refresh_landing_stats()


@db_periodic_task(crontab(minute='40'), priority=10)
def warm_pesticide_caches():
    # The pass itself runs on the secondary queue: after a rebuild it renders
    # every warm page (a couple of minutes), which would hold up the primary
    # queue's every-minute tasks.
    warm_pesticide_caches_now()


@db_task(queue='secondary', priority=10)
def warm_pesticide_caches_now():
    from camp.apps.pesticides import warm
    with get_queue('secondary').lock_task('warm-pesticide-caches'):
        warm.warm()
