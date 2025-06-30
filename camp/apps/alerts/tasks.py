from django_huey import db_task, db_periodic_task
from huey import crontab
from django.utils import timezone
from django.db.models import Q

from camp.apps.alerts.logic.evaluator import AlertEvaluator
from camp.apps.alerts.models import Alert
from camp.apps.monitors.models import Monitor


@db_periodic_task(crontab(minute='*/10'), priority=100)
def periodic_alerts():
    """
    Every 10 minutes:
    - Update or end any active alerts.
    - Create alerts for active monitors that don’t currently have one.
    """

    # Part 1: Update existing alerts
    active_alerts = (Alert.objects
        .filter(end_time__isnull=True)
        .select_related('monitor')
    )

    for alert in active_alerts:
        AlertEvaluator(alert.monitor).evaluate()

    # Part 2: Check for new alerts for monitors without alerts
    for monitor_model in Monitor.get_subclasses():
        monitors = (monitor_model.objects
            .get_active()
            .exclude(alerts__end_time__isnull=True)
        )

        for monitor in monitors:
            AlertEvaluator(monitor).evaluate()
