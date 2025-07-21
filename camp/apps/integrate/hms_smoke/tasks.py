from datetime import timedelta
from django.conf import settings
from django_huey import db_periodic_task
from django.utils import timezone
from huey import crontab

from .data import get_smoke_file

""" 
    Function will retrieve the zip from HMS NOAA system, and unzip/save new objects
"""

#Query every hour from hours 1am-3am and  8am-4pm
#NOAA data is available from 8-9am to 2-3am the next day PST
@db_periodic_task(crontab(minute='0', hour='0-3,15-23'), priority=50)
def fetch_files():
    get_smoke_file(timezone.now().astimezone(settings.DEFAULT_TIMEZONE).date())
    
#Query 1pm pst for the previous days final data 
#data usually available around 8am pst, but just in case the data is late
@db_periodic_task(crontab(minute='0', hour='17'), priority=50)
def final_file():
    get_smoke_file(timezone.now().astimezone(settings.DEFAULT_TIMEZONE).date() - timedelta(days=1))
    