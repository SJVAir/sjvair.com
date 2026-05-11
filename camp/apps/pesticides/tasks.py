from django_huey import db_periodic_task
from huey import crontab


@db_periodic_task(crontab(minute='0', hour='14'), priority=50)
def fetch_pesticide_notices():
    from camp.apps.pesticides.spraydays import fetch_applications
    fetch_applications()
