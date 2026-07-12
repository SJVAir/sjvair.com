from random import choice

from django_huey import db_task, db_periodic_task
from huey import crontab
from django.conf import settings
from django.urls import reverse
from django.utils import timezone
from django.db.models import Q

import twilio.rest

from camp.apps.alerts.evaluator import AlertEvaluator
from camp.apps.alerts.models import Alert, Notification
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


@db_task(priority=100)
def send_alert_notification(notification_id):
    notification = Notification.objects.select_related('user').get(pk=notification_id)

    twilio_client = twilio.rest.Client(
        settings.TWILIO_ACCOUNT_SID,
        settings.TWILIO_AUTH_TOKEN
    )

    try:
        message = twilio_client.messages.create(
            to=str(notification.user.phone),
            from_=choice(settings.TWILIO_PHONE_NUMBERS),
            body=notification.message,
            status_callback=f'https://sjvair.com{reverse("twilio-status-callback")}',
        )
    except Exception as exc:
        # Broad on purpose: network failures (timeouts, DNS, connection
        # resets) aren't guaranteed to surface as TwilioRestException, and
        # any unhandled exception here leaves the notification stuck at
        # QUEUED forever with no record of why it failed.
        notification.status = Notification.Status.FAILED
        notification.error = str(exc)
        notification.save(update_fields=['status', 'error'])
        return

    notification.status = Notification.Status.SENT
    notification.sent_at = timezone.now()
    notification.provider_id = message.sid
    notification.save(update_fields=['status', 'sent_at', 'provider_id'])
