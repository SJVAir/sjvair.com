from datetime import timedelta

from django.utils import timezone

from django_huey import db_task, db_periodic_task
from huey import crontab

from camp.apps.monitors.models import Monitor


@db_periodic_task(crontab(hour='*', minute='15'), priority=50)
def hourly_health_checks(hour=None):
    """
    Run QA/QC health checks for all PM2.5 monitors with multiple sensors.

    Runs at minute 15 (not right at the hour) because get_for_health_checks()
    only queues a monitor if it already has RAW PM2.5 entries for the target
    hour: VOZbox's upstream only publishes a hard batch ~65 min after each
    hour closes (see camp/apps/monitors/vozbox/tasks.py), and import_realtime
    pulls it in on its next */10 min cycle -- landing in the DB around minute
    10-11 of the following hour. Running at minute 1 fired before that batch
    existed, so VOZbox never accumulated passing HealthCheck rows and was
    permanently excluded from filter_healthy() (e.g. the pm25/current/ API).
    """
    if hour is None:
        this_hour = timezone.now().replace(minute=0, second=0, microsecond=0)
        hour = this_hour - timedelta(hours=1)

    queryset = Monitor.objects.get_for_health_checks(hour)
    for monitor in queryset:
        monitor_health_check(monitor.pk, hour)


@db_task(priority=50)
def monitor_health_check(monitor_id, hour):
    monitor = Monitor.objects.get(pk=monitor_id)
    monitor.run_health_check(hour)
