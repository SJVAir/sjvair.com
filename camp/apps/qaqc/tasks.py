from datetime import timedelta

from django.utils import timezone

from django_huey import db_task, db_periodic_task
from huey import crontab

from camp.apps.entries.models import PM25
from camp.apps.monitors.models import Monitor


@db_periodic_task(crontab(hour='*', minute='1'), priority=50)
def hourly_health_checks(hour=None):
    """
    Run QA/QC health checks for all PM2.5 monitors with multiple sensors.
    """
    if hour is None:
        this_hour = timezone.now().replace(minute=0, second=0, microsecond=0)
        last_hour = this_hour - timedelta(hours=1)

    subclasses = Monitor.get_subclasses()

    for monitor_class in subclasses:
        sensors = monitor_class.ENTRY_CONFIG.get(PM25, {}).get('sensors', [])
        if len(sensors) < 2:
            continue

        for monitor in monitor_class.objects.all():
            monitor_health_check(monitor.pk, last_hour)

@db_task
def monitor_health_check(monitor_id, hour):
    monitor = Monitor.objects.get(pk=monitor_id)
    monitor.run_health_check(hour)




# @db_periodic_task(crontab(hour='8', minute='30'), priority=50)
# def ab_regression():
#     qs = Monitor.objects.get_active_multisensor()

#     for monitor in qs:
#         linreg = ABLinearRegression(monitor)
#         analysis = linreg.analyze()

#         if analysis is not None:
#             analysis.save_as_current()

