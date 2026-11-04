from datetime import datetime, timedelta, timezone as dt_timezone

from django.conf import settings
from django.utils import timezone

from camp.utils.datetime import localtime

# Huey crontabs run in UTC. A Pacific hour lands on one of two UTC hours
# depending on DST, so each rollup is scheduled on both and guarded with
# is_pacific_hour(). Keys are the Pacific hour, values the UTC hours that
# contain it in PDT and PST.
ROLLUP_UTC_HOURS = {1: '8,9', 2: '9,10'}


def is_pacific_hour(hour, now=None):
    """
    True when `now` falls in the given Pacific hour. The repeated hour on
    the fall-back day counts once (fold 0 only).
    """
    local = localtime(now or timezone.now())
    return local.hour == hour and local.fold == 0


# How long after a period ends its latest scheduled rollup runs (Pacific
# wall-clock offsets from the period's end). Hour is the region task at H+1:50.
ROLLUP_LOCAL_TIME = {
    'hour': timedelta(minutes=50),
    'day': timedelta(hours=1, minutes=10),
    'month': timedelta(hours=1, minutes=25),
    'quarter': timedelta(hours=1, minutes=35),
    'season': timedelta(hours=1, minutes=55),
    'year': timedelta(hours=2, minutes=5),
}

# After period end plus this margin, a period's rollups are done and its
# summaries won't change. Each covers ROLLUP_LOCAL_TIME plus an hour of slack.
SETTLE_MARGIN = {
    'hour': timedelta(hours=2),
    'day': timedelta(hours=3),
    'month': timedelta(hours=4),
    'quarter': timedelta(hours=4),
    'season': timedelta(hours=4),
    'year': timedelta(hours=5),
}


def _pacific_midnight(year, month, day=1):
    return timezone.make_aware(datetime(year, month, day), settings.DEFAULT_TIMEZONE)


def period_end(resolution, ts):
    """
    The end of the period of the given resolution that contains `ts`, as an
    aware datetime. Day and coarser are Pacific boundaries built from calendar
    values, never timedelta arithmetic across DST.
    """
    if resolution == 'hour':
        start = ts.astimezone(dt_timezone.utc).replace(minute=0, second=0, microsecond=0)
        return start + timedelta(hours=1)

    local = localtime(ts)
    if resolution == 'day':
        nxt = local.date() + timedelta(days=1)
        return _pacific_midnight(nxt.year, nxt.month, nxt.day)
    if resolution == 'month':
        return _pacific_midnight(local.year + (local.month == 12), local.month % 12 + 1)
    if resolution == 'quarter':
        first = (local.month - 1) // 3 * 3 + 4
        return _pacific_midnight(local.year + (first > 12), (first - 1) % 12 + 1)
    if resolution == 'season':
        # Dec-Feb, Mar-May, Jun-Aug, Sep-Nov: each ends on the 1st of Mar/Jun/Sep/Dec.
        if local.month == 12:
            return _pacific_midnight(local.year + 1, 3)
        end_month = (local.month // 3 + 1) * 3 if local.month >= 3 else 3
        return _pacific_midnight(local.year, end_month)
    if resolution == 'year':
        return _pacific_midnight(local.year + 1, 1)
    raise ValueError(f'Unknown resolution: {resolution}')


def is_settled(resolution, range_end, now=None):
    """
    True when every period in a range ending at `range_end` (exclusive) has
    had time to finish its rollups. An open range (None) is never settled.
    """
    if range_end is None:
        return False
    last_period_end = period_end(resolution, range_end - timedelta(microseconds=1))
    return (now or timezone.now()) >= last_period_end + SETTLE_MARGIN[resolution]
