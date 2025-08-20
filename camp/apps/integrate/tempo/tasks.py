from datetime import timedelta
from django.conf import settings
from django_huey import db_periodic_task
from django.utils import timezone
from huey import crontab

from camp.apps.integrate.tempo.data import tempo_data

#query for new data every 3 hrs, from the previous day 

@db_periodic_task(crontab(minute='0', hour='*/3'), priority=50)
def fetch_no2_data():
    now = timezone.now().astimezone(settings.TIME_ZONE)
    before = now - timedelta(hours=24)
    tempo_data('no2', before, now)
    
@db_periodic_task(crontab(minute='0', hour='*/3'), priority=50)
def fetch_hcho_data():
    now = timezone.now().astimezone(settings.TIME_ZONE)
    before = now - timedelta(hours=24)
    tempo_data('hcho', before, now)
    
@db_periodic_task(crontab(minute='0', hour='*/3'), priority=50)
def fetch_o3tot_data():
    now = timezone.now().astimezone(settings.TIME_ZONE)
    before = now - timedelta(hours=24)
    tempo_data('o3tot', before, now)
    