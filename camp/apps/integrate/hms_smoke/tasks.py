from django_huey import db_periodic_task
from huey import crontab
from .services.data import get_smoke_file
from django.utils import timezone

""" 
    Function will retrieve the zip from HMS NOAA system, and unzip/save new objects
"""



# Read the env variable safely and once

#rm
# env = os.environ.get
# query_hours = int(os.environ.get('query_hours', 3))

@db_periodic_task(crontab(minute='0', hour=f'*/12-20'), priority=50)
def fetch_files():
    get_smoke_file(timezone.now())
    