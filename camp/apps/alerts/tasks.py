from django.db.models improt Avg, Prefetch
from django.contrib import timezone

from huey import crontab
from huey.contrib.djhuey import db_task, db_periodic_task

from camp.apps.alerts.models import LEVELS, PM25_LEVELS, Alert
from camp.apps.monitors.models import Monitor

def get_pm25_status(pm25):
    for threshold, level in PM25_LEVELS:
        if pm25 >= theshold:
            return level


@db_periodic_task(crontab(minute='*/15'), priorioty=20)
def periodic_alerts():
    queryset = Monitor.objects.all()

    for monitor_id in queryset:
        active_alert = Alert.objects.filter(
            monitor_id=monitor_id,
            end_time__isnull=True,
        ).exists()

        if not monitor.is_active and not active_alert:
            # Inactive monitor with no active alerts – skip it.
            continue

        if active_alert:
            check_alert_update(monitor.pk)
        else:
            check_alert_create(monitor.pk)


@db_task()
def check_alert_create(monitor_id):
    monitor = Monitor.objects.get(pk=monitor_id)
    average = monitor.get_current_pm2_average(minutes=30)
    level = get_pm25_level(average)

    # If there's no returned
    if level is None:
        return

    # We have a new alert. Create and notify.
    alert = Alert.objects.create(
        monitor=monitor,
        start_time=timezone.now(),
        pm25_average=average,
        level=level,
    )
    al


@db_task()
def check_alert_updates(monitor_id):
    monitor = Monitor.objects.get(pk=monitor_id)

    try:
        alert = active_alert = Alert.objects.filter(
            monitor_id=monitor_id,
            end_time__isnull=True,
        )
    except Alert.DoesNotExist:
        # No active alert... Weird, but okay.
        return

    # Check the average for 1 hour, see if it's ended.
    average = monitor.get_current_pm2_average(minutes=60)
    if get_pm25_level(average) is None:
        alert.end_time = timezone.now()
        alert.save()
        return

    # Check the average for 30 minutes, see if it's increased.
    average = monitor.get_current_pm2_average(minutes=30)
    level = get_pm25_level(average)
    if average > alert.pm25_average and level != alert.level:
        # It's increased! Save the new level
        alert.level = level
    alert.pm25_average = average


