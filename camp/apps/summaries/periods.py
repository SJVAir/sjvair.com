from collections.abc import Iterator
from datetime import datetime, timedelta, timezone as dt_timezone

from django.conf import settings

from camp.utils.datetime import localtime, make_aware


def _pacific_midnight(year, month, day=1):
    return make_aware(datetime(year, month, day), settings.DEFAULT_TIMEZONE)


def period_end(resolution, ts):
    """
    The end of the period of the given resolution that contains `ts`, as an
    aware datetime. Day and coarser are Pacific boundaries built from calendar
    values, never timedelta arithmetic across DST.
    """
    if resolution == 'hour':
        # Hours are absolute: truncating in UTC is intentional (Pacific offsets are whole hours).
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


def period_start(resolution, ts):
    """
    The start of the period of the given resolution that contains `ts`. Hours
    truncate in UTC; everything else is a Pacific midnight built from calendar
    values.
    """
    if resolution == 'hour':
        return ts.astimezone(dt_timezone.utc).replace(minute=0, second=0, microsecond=0)

    local = localtime(ts)
    if resolution == 'day':
        return _pacific_midnight(local.year, local.month, local.day)
    if resolution == 'month':
        return _pacific_midnight(local.year, local.month)
    if resolution == 'quarter':
        return _pacific_midnight(local.year, (local.month - 1) // 3 * 3 + 1)
    if resolution == 'season':
        # Dec-Feb, Mar-May, Jun-Aug, Sep-Nov.
        if local.month < 3:
            return _pacific_midnight(local.year - 1, 12)
        return _pacific_midnight(local.year, local.month // 3 * 3)
    if resolution == 'year':
        return _pacific_midnight(local.year, 1)
    raise ValueError(f'Unknown resolution: {resolution}')


def is_period_start(resolution, ts):
    return period_start(resolution, ts) == ts


def iter_period_starts(resolution, start, end) -> Iterator[datetime]:
    """Starts of every period overlapping [start, end), ascending. The first may precede `start`."""
    current = period_start(resolution, start)
    while current < end:
        yield current
        current = period_end(resolution, current)


def iter_hours(start, end) -> Iterator[datetime]:
    """Each UTC hour in [start, end), as UTC-aware datetimes."""
    current = period_start('hour', start)
    end = end.astimezone(dt_timezone.utc)
    while current < end:
        yield current
        current += timedelta(hours=1)
