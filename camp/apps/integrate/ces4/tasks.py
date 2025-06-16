
#Single task to process shape files into the db
#huey db_task?
#create the functions in services.data then import
from django_huey import db_task
from .data import CalEnviroToDB


@db_task()
def CalEnviroScreen4Load():
    CalEnviroToDB()

  

