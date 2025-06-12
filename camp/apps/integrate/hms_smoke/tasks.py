from django_huey import db_periodic_task
from django.utils import timezone
from huey import crontab

from .data import get_smoke_file

""" 
    Function will retrieve the zip from HMS NOAA system, and unzip/save new objects
"""

@db_periodic_task(crontab(minute='0', hour='9-12,15-23'), priority=50)
def fetch_files():
    get_smoke_file(timezone.now())
    