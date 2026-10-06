import logging
import re
import unicodedata
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Count
from django.utils import timezone
from django.utils.translation import gettext as _

from camp.apps.alerts.models import Alert, Notification, Subscription
from camp.utils.datetime import localtime

logger = logging.getLogger(__name__)

# At most one text per subscription per MIN_INTERVAL, unless the level
# jumps BYPASS_RANKS or more above the last one texted.
MIN_INTERVAL = timedelta(hours=2)
BYPASS_RANKS = 2
# At most this many alert texts per subscription per local (Pacific) day,
# unless the level jumps BYPASS_RANKS or more above the last one texted.
DAILY_CAP = 3
# A subscription re-arms (can be texted again at a level it already got)
# once the monitor has stayed below its threshold this long.
RESET_AFTER = timedelta(hours=2)
# Local (Pacific) hour for the daily "still bad" reminder.
REMINDER_HOUR = 10


def get_recipients(monitor):
    return (Subscription.objects
        .filter(monitor_id=monitor.pk, user__phone_verified=True)
        .exclude(user__phone='')
        .select_related('user')
    )


def get_monitor_level(levels):
    '''
    Return (entry_model, level) for the monitor's worst pollutant, or
    (None, None) if no pollutant has a level right now.
    '''
    known = [(entry_model, level) for entry_model, level in levels.items() if level is not None]
    if not known:
        return None, None
    return max(known, key=lambda item: item[1].rank)


def get_alert_level(subscription, level, now, alerts_today=0):
    '''
    Escalation rule for one subscription. Updates the subscription's
    tracking fields (the caller saves) and returns the level to text, or
    None. Never texts when the air improves. `alerts_today` is how many
    alert texts this subscription has had since local midnight.
    '''
    threshold = subscription.get_threshold()
    last = subscription.get_last_notified_level()

    if level < threshold:
        if subscription.below_threshold_since is None:
            subscription.below_threshold_since = now
        elif now - subscription.below_threshold_since >= RESET_AFTER:
            subscription.last_notified_level = ''
        return None

    subscription.below_threshold_since = None
    if last is not None and level <= last:
        return None

    if subscription.last_notified_at and now - subscription.last_notified_at < MIN_INTERVAL:
        floor = last.rank if last is not None else threshold.rank - 1
        if level.rank - floor < BYPASS_RANKS:
            return None

    # The cap bypass needs a real baseline: a rise of BYPASS_RANKS above the
    # last text. A re-armed subscription (no last text) has none.
    if alerts_today >= DAILY_CAP:
        if last is None or level.rank - last.rank < BYPASS_RANKS:
            return None

    return level


def get_reminder_level(subscription, level, now):
    '''
    Daily "still bad" rule: only for a subscription that hasn't re-armed,
    is still at or above its threshold, and hasn't been texted about this
    monitor yet today (Pacific). Returns the current level, which may be
    lower than the last one texted.
    '''
    if not subscription.last_notified_level or level < subscription.get_threshold():
        return None

    start_of_day = localtime(now).replace(hour=0, minute=0, second=0, microsecond=0)
    if subscription.last_notified_at and subscription.last_notified_at >= start_of_day:
        return None
    return level


SMS_CHAR_MAP = str.maketrans({
    '\u2018': "'", '\u2019': "'", '\u201c': '"', '\u201d': '"',
    '\u2013': '-', '\u2014': '-', '\u2026': '...',
})


# ASCII printables that are not in the GSM-7 basic set (extension table or absent).
NOT_GSM_7_BASIC = set('[]{}\\^~|`')


def sms_safe(text, max_length=60):
    '''
    Reduce owner-set text to plain ASCII so one stray character (accent,
    curly quote, emoji) can't force UCS-2 and double the billed segments.
    '''
    text = unicodedata.normalize('NFKD', text.translate(SMS_CHAR_MAP))
    text = ''.join(char for char in text if ord(char) < 128 and char.isprintable() and char not in NOT_GSM_7_BASIC)
    text = re.sub(r'\s+', ' ', text).strip()
    if len(text) > max_length:
        text = text[:max_length - 3].rstrip() + '...'
    return text


def build_message(monitor, entry_model, level, kind):
    # Plain GSM-7 text: one emoji would force UCS-2 and double the billed segments.
    params = {'level': level.label, 'pollutant': entry_model.label, 'name': sms_safe(monitor.name)}
    if kind == Notification.Kind.REMINDER:
        first_line = _('SJVAir: Air quality is still {level} ({pollutant}) at {name}.')
    else:
        first_line = _('SJVAir alert: Air quality is {level} ({pollutant}) at {name}.')

    lines = [first_line.format(**params)]
    if level.guidance:
        lines.append(str(level.guidance))
    lines.append(f'https://www.sjvair.com{monitor.get_absolute_url()}')
    return '\n'.join(lines)


def get_driving_update(monitor, entry_model):
    alert = (Alert.objects
        .filter(monitor_id=monitor.pk, entry_type=entry_model.entry_type, end_time__isnull=True)
        .select_related('latest')
        .first()
    )
    return alert.latest if alert else None


def get_alerts_today(monitor, now):
    '''Alert-kind texts since local midnight, as {subscription_id: count}; one query per monitor.'''
    start_of_day = localtime(now).replace(hour=0, minute=0, second=0, microsecond=0)
    rows = (Notification.objects
        .filter(subscription__monitor_id=monitor.pk, kind=Notification.Kind.ALERT, created__gte=start_of_day)
        .values('subscription_id')
        .annotate(total=Count('pk'))
    )
    return {row['subscription_id']: row['total'] for row in rows}


def process_subscriptions(monitor, levels, rule, kind, daily_cap=False):
    '''
    Run `rule(subscription, level, now) -> Level | None` for every recipient
    of this monitor, and queue a text for each level it returns. Rows are
    locked so a concurrent alert run and reminder run can't both text the
    same subscription. With `daily_cap`, the rule also gets `alerts_today`
    (reminder rules keep their three-argument signature).
    '''
    if not settings.SEND_SMS_ALERTS:
        return []

    entry_model, level = get_monitor_level(levels)
    if level is None:
        return []

    from camp.apps.alerts import tasks

    now = timezone.now()
    queued = []
    todays = get_alerts_today(monitor, now) if daily_cap else {}
    with transaction.atomic():
        for subscription in get_recipients(monitor).select_for_update(of=('self',)):
            before = (
                subscription.last_notified_level,
                subscription.last_notified_at,
                subscription.below_threshold_since,
            )
            if daily_cap:
                send_level = rule(subscription, level, now, alerts_today=todays.get(subscription.pk, 0))
            else:
                send_level = rule(subscription, level, now)
            alert_update = None
            if send_level is not None:
                alert_update = get_driving_update(monitor, entry_model)

            if send_level is not None and alert_update is None:
                logger.warning(
                    'No open %s alert on monitor %s; not texting subscription %s',
                    entry_model.entry_type, monitor.pk, subscription.pk,
                )
            elif send_level is not None:
                notification = Notification.objects.create(
                    alert_update=alert_update,
                    subscription=subscription,
                    user=subscription.user,
                    kind=kind,
                    created=now,
                    level=send_level.key,
                    message=build_message(monitor, entry_model, send_level, kind),
                )
                subscription.last_notified_level = send_level.key
                subscription.last_notified_at = now
                # Enqueue only once the row is committed, so the worker can see it.
                transaction.on_commit(
                    lambda pk=notification.pk: tasks.send_alert_notification(pk)
                )
                queued.append(notification)

            after = (
                subscription.last_notified_level,
                subscription.last_notified_at,
                subscription.below_threshold_since,
            )
            if after != before:
                subscription.save(update_fields=[
                    'last_notified_level', 'last_notified_at', 'below_threshold_since',
                ])
    return queued


def notify_subscribers(monitor, levels):
    return process_subscriptions(monitor, levels, get_alert_level, Notification.Kind.ALERT, daily_cap=True)


def send_reminders(monitor, levels):
    return process_subscriptions(monitor, levels, get_reminder_level, Notification.Kind.REMINDER)
