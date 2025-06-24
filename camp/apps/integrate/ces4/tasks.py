from django_huey import db_task

from .data import Ces4Processing


@db_task()
def CalEnviroScreen4Load():
    Ces4Processing.ces4_request_db()
