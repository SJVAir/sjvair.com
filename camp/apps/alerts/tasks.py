from django.db.models import Avg, Prefetch
from django.utils import timezone

from huey import crontab
from huey.contrib.djhuey import db_task, db_periodic_task

from camp.apps.alerts.models import LEVELS, PM25_LEVELS, Alert
from camp.apps.monitors.models import Monitor

def get_pm25_level(pm25):
    if pm25:
        for threshold, level in PM25_LEVELS:
            if pm25 >= threshold:
                return level


@db_periodic_task(crontab(minute='*/10'), priority=100)
def periodic_alerts():
    queryset = Monitor.objects.all()

    for monitor in queryset:
        active_alert = Alert.objects.filter(
            monitor_id=monitor.pk,
            end_time__isnull=True,
        ).exists()

        if not monitor.is_active and not active_alert:
            # Inactive monitor with no active alerts – skip it.
            continue

        if active_alert:
            # There's an active alert, so check if we need
            # to update or end it.
            check_alert_update(monitor.pk)
        else:
            # No current alert, check to see if we need to
            # create one.
            check_alert_create(monitor.pk)


@db_task(priority=50)
def check_alert_create(monitor_id):
    monitor = Monitor.objects.get(pk=monitor_id)
    active_alert = monitor.alerts.filter(end_time__isnull=True).exists()

    if active_alert:
        return

    average = monitor.get_current_pm25_average(minutes=30)
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
    alert.send_notifications()


@db_task(priority=50)
def check_alert_update(monitor_id):
    monitor = Monitor.objects.get(pk=monitor_id)

    try:
        alert = Alert.objects.get(
            monitor_id=monitor_id,
            end_time__isnull=True,
        )
    except Alert.DoesNotExist:
        # No active alert... Weird, but okay.
        return

    # Check the average for 1 hour, see if it's ended.
    average = monitor.get_current_pm25_average(minutes=60)
    if get_pm25_level(average) is None:
        alert.pm25_average = average
        alert.end_time = timezone.now()
        alert.save()
        return

    # Check the average for 30 minutes, see if it's increased.
    send_notifications = False
    average = monitor.get_current_pm25_average(minutes=30)
    level = get_pm25_level(average)
    if average > alert.pm25_average and level != alert.level:
        # It's increased! Save the new level
        alert.level = level
        send_notifications = True
    alert.pm25_average = average
    alert.save()

    if send_notifications:
        alert.send_notifications()
