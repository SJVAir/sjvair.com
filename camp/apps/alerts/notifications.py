from django.conf import settings
from django.utils.translation import gettext as _

from camp.apps.alerts import tasks
from camp.apps.alerts.models import Notification, Subscription
from camp.apps.entries.levels import AQLevel


def get_recipients(alert):
    return (Subscription.objects
        .filter(monitor_id=alert.monitor_id)
        .select_related('user')
    )


def notify_subscribers(alert_update):
    if not settings.SEND_SMS_ALERTS:
        return

    alert = alert_update.alert
    level = alert_update.get_level()

    icon = '✅' if level == AQLevel.scale.GOOD else '⚠️'
    message = '\n'.join([
        _('{icon} Air Quality Alert for {name} in {county} County').format(
            icon=icon,
            name=alert.monitor.name,
            county=alert.monitor.county,
        ),
        f'{alert.entry_model.label}: {level.label}',
        f'{level.guidance}\n' or '',
        f'🔗 https://sjvair.com{alert.monitor.get_absolute_url()}',
    ])

    for subscription in get_recipients(alert):
        sub_level = AQLevel.scale[subscription.level.upper()]
        if level < sub_level:
            continue

        notification = Notification.objects.create(
            alert_update=alert_update,
            subscription=subscription,
            user=subscription.user,
            message=message,
        )
        tasks.send_alert_notification(notification.pk)
