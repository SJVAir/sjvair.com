from datetime import timedelta
from django_huey import db_periodic_task
from django.utils import timezone
from huey import crontab

from .data import get_smoke_file

""" 
    Function will retrieve the zip from HMS NOAA system, and unzip/save new objects
"""

#Query every hour from hours 1am-3am and  8am-4pm
#NOAA data is available from 8-9am to 2-3am the next day PST
@db_periodic_task(crontab(minute='0', hour='8-10,15-23'), priority=50)
def fetch_files():
    get_smoke_file(timezone.now().date())
    
#Query 9am est for the previous days data 
@db_periodic_task(crontab(minute='0', hour='4'), priority=50)
def final_file():
    get_smoke_file(timezone.now().date() - timedelta(days=1))