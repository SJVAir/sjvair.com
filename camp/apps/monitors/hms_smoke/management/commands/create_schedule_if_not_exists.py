from django.core.management.base import BaseCommand
from django_q.models import Schedule

"""
    Script to create a scheduler if it doesnt exist.
    This should be ran after making migrations, and before runserver/qcluster
    To ensure there is a job in queue according to the schedule.
    
    Function will retrieve the zip from HMS NOAA system, and unzip/save new objects
"""
import environ 
env = environ.Env()
environ.Env.read_env() 

class Command(BaseCommand):
    help = 'Creates the data retrieval schedule if it does not exist'

    def handle(self):
        if not Schedule.objects.filter(name="retrieve-data-scheduler").exists():
            Schedule.objects.create(
                name='retrieve-data-scheduler',
                func='SmokeTest.services.data.get_todays_smoke_file',
                schedule_type=Schedule.MINUTES,   
                minutes= env('query_hours'),
                repeats=-1,
            )
            self.stdout.write(self.style.SUCCESS('Scheduler created.'))
        else:
            self.stdout.write('Scheduler already exists.')