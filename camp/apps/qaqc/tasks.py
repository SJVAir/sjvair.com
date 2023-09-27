from django_huey import db_periodic_task
from huey import crontab

from camp.apps.qaqc.ablinreg import ABLinearRegression
from camp.apps.monitors.models import Monitor


@db_periodic_task(crontab(hour='8', minute='30'), priority=50)
def ab_regression():
    qs = Monitor.objects.get_active_multisensor()

    for monitor in qs:
        linreg = ABLinearRegression(monitor)
        analysis = linreg.analyze()

        if analysis is not None:
            analysis.save_as_current()

