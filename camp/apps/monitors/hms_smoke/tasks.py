import os
from django_huey import db_periodic_task
from huey import crontab
from .services.data import get_smoke_file

""" 
    Function will retrieve the zip from HMS NOAA system, and unzip/save new objects
"""

env = os.environ.get

# Read the env variable safely and once
query_hours = int(os.environ.get('query_hours', 3))

@db_periodic_task(crontab(minute='0', hour=f'*/{query_hours}'), priority=50)
def fetch_files():
    get_smoke_file()
    