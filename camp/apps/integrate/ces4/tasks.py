from django_huey import db_task

from .data import Ces4Data


@db_task()
def ces4_load():
    Ces4Data.ces4_request()
