import logging
from contextlib import contextmanager
from random import choice
from uuid import uuid4

from django_huey import db_task, db_periodic_task
from huey import crontab
from django.conf import settings
from django.core.cache import cache
from django.urls import reverse
from django.utils import timezone

import twilio.rest

from camp.apps.alerts import notifications
from camp.apps.alerts.evaluator import AlertEvaluator
from camp.apps.alerts.models import Alert, Notification, Subscription
from camp.apps.monitors.models import Monitor
from camp.utils.datetime import localtime

logger = logging.getLogger(__name__)


@contextmanager
def expiring_lock(key, timeout):
    '''
    A cache-backed lock that expires on its own after `timeout` seconds, so a
    worker killed mid-run (huey's own lock has no TTL and is only released
    on exit) can't block every later run. Yields True if acquired, False if
    another run holds it. Only releases a lock that is still ours.
    '''
    token = uuid4().hex
    if not cache.add(key, token, timeout):
        logger.info('Lock %s: previous run still holds lock, skipping', key)
        yield False
        return

    try:
        yield True
    finally:
        if cache.get(key) == token:
            cache.delete(key)


def get_alert_monitors():
    '''
    Every monitor that needs evaluating, each exactly once: active monitors
    of every type that has alertable entry types, plus any monitor with an
    open alert (so alerts on monitors that went offline can still close).
    '''
    open_alert_ids = set(Alert.objects
        .filter(end_time__isnull=True)
        .values_list('monitor_id', flat=True)
    )
    seen = set()
    for monitor_model in Monitor.get_subclasses():
        if not monitor_model.alertable_entry_types:
            continue

        active_ids = set(monitor_model.objects.get_active().values_list('pk', flat=True))
        for monitor in monitor_model.objects.filter(pk__in=active_ids | open_alert_ids):
            if monitor.pk not in seen:
                seen.add(monitor.pk)
                yield monitor


@db_periodic_task(crontab(minute='*/10'), priority=100)
def periodic_alerts():
    '''
    Every 10 minutes: bring every relevant monitor's alerts up to date, then
    apply the subscriber texting rules to monitors anyone subscribes to.
    Locked so a slow run can't overlap the next one.
    '''
    with expiring_lock('alerts:periodic-alerts-lock', 9 * 60) as acquired:
        if not acquired:
            return

        subscribed_ids = set(Subscription.objects.values_list('monitor_id', flat=True))
        for monitor in get_alert_monitors():
            try:
                levels = AlertEvaluator(monitor).evaluate()
                if monitor.pk in subscribed_ids:
                    notifications.notify_subscribers(monitor, levels)
            except Exception:
                logger.exception('Alert run failed for monitor %s', monitor.pk)


@db_periodic_task(crontab(minute='0', hour='17,18'), priority=100)
def daily_reminders():
    '''
    10 AM Pacific "still bad" reminders for multi-day events. Huey crontabs
    run in UTC, so this fires at both 17:00 and 18:00 UTC and only
    proceeds in the run that is 10 AM locally (PDT vs PST).
    '''
    if localtime().hour != notifications.REMINDER_HOUR:
        return

    with expiring_lock('alerts:daily-reminders-lock', 50 * 60) as acquired:
        if not acquired:
            return

        monitor_ids = (Subscription.objects
            .exclude(last_notified_level='')
            .values_list('monitor_id', flat=True)
            .distinct()
        )
        for monitor in Monitor.objects.filter(pk__in=list(monitor_ids)):
            try:
                levels = AlertEvaluator(monitor).get_levels()
                notifications.send_reminders(monitor, levels)
            except Exception:
                logger.exception('Daily reminder failed for monitor %s', monitor.pk)


@db_task(priority=100)
def send_alert_notification(notification_id):
    notification = Notification.objects.select_related('user').get(pk=notification_id)

    twilio_client = twilio.rest.Client(
        settings.TWILIO_ACCOUNT_SID,
        settings.TWILIO_AUTH_TOKEN
    )

    try:
        # Hardcoded production host, not settings/Site-derived: this URL
        # must exactly match what Twilio signs, and Twilio's status
        # callback always hits production regardless of which environment
        # queued the notification. Must be www: the apex sjvair.com is a
        # Squarespace 301 that never reaches Django.
        message = twilio_client.messages.create(
            to=str(notification.user.phone),
            from_=choice(settings.TWILIO_PHONE_NUMBERS),
            body=notification.message,
            status_callback=f'https://www.sjvair.com{reverse("twilio-status-callback")}',
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
