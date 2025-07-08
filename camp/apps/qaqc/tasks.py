from datetime import timedelta

from django.utils import timezone

from django_huey import db_task, db_periodic_task
from huey import crontab

from camp.apps.monitors.models import Monitor


@db_periodic_task(crontab(hour='*', minute='1'), priority=50)
def hourly_health_checks(hour=None):
    """
    Run QA/QC health checks for all PM2.5 monitors with multiple sensors.
    """
    if hour is None:
        this_hour = timezone.now().replace(minute=0, second=0, microsecond=0)
        hour = this_hour - timedelta(hours=1)

    queryset = Monitor.objects.get_for_health_checks()
    for monitor in queryset:
        monitor_health_check(monitor.pk, hour)

@db_task(priority=50)
def monitor_health_check(monitor_id, hour):
    monitor = Monitor.objects.get(pk=monitor_id)
    monitor.run_health_check(hour)
