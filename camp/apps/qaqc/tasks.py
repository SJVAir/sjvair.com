from huey import crontab
from huey.contrib.djhuey import db_periodic_task

from camp.apps.qaqc.sensorlinreg import SensorLinearRegression
from camp.apps.monitors.models import Monitor


@db_periodic_task(crontab(hour='8', minute='30'), priority=50)
def ab_regression():
    qs = Monitor.objects.get_active_multisensor()

    for monitor in qs:
        linreg = SensorLinearRegression(monitor)
        report = linreg.generate_regression()

        if report != None:
            report.save()

