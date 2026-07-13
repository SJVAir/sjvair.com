from datetime import datetime, timedelta

from django.conf import settings

from camp.utils.datetime import make_aware
from camp.apps.summaries.models import BaseSummary


CHUNK_DAYS = 7


def chunk_start_for(cursor, range_start):
    """The lower bound of the next chunk to process, walking backward from cursor."""
    return max(cursor - timedelta(days=CHUNK_DAYS), range_start)


def hour_range(start, end):
    """Yield each hourly datetime in [start, end)."""
    current = start
    while current < end:
        yield current
        current += timedelta(hours=1)


def iter_chunk_days(chunk_start, chunk_end):
    """Yield each day (midnight-aligned datetime) in [chunk_start, chunk_end)."""
    day = chunk_start
    while day < chunk_end:
        yield day
        day += timedelta(days=1)


def _months_later(day, months):
    """Advance a day-1-aligned datetime by `months` calendar months, re-localizing for DST."""
    total = day.month - 1 + months
    year = day.year + total // 12
    month = total % 12 + 1
    return make_aware(datetime(year, month, 1), settings.DEFAULT_TIMEZONE)


def daily_rollup_window(day):
    """The (target, source, window_start, window_end) tuple to roll up a single day."""
    return (BaseSummary.Resolution.DAILY, BaseSummary.Resolution.HOURLY, day, day + timedelta(days=1))


def higher_rollup_windows(day):
    """
    Return the (target, source, window_start, window_end) rollup windows that
    become fully covered once `day` — the earliest day of a chunk, walking
    backward — has been processed. Empty unless `day` is the first of a
    month: only then can a month (and possibly quarter/season/year) be
    confirmed complete, since every later day in that period was necessarily
    already processed on an earlier (more recent) tick.
    """
    if day.day != 1:
        return []

    windows = [(
        BaseSummary.Resolution.MONTHLY, BaseSummary.Resolution.DAILY,
        day, _months_later(day, 1),
    )]

    if day.month in (1, 4, 7, 10):
        windows.append((
            BaseSummary.Resolution.QUARTERLY, BaseSummary.Resolution.MONTHLY,
            day, _months_later(day, 3),
        ))

    if day.month in (12, 3, 6, 9):
        windows.append((
            BaseSummary.Resolution.SEASONAL, BaseSummary.Resolution.MONTHLY,
            day, _months_later(day, 3),
        ))

    if day.month == 1:
        windows.append((
            BaseSummary.Resolution.YEARLY, BaseSummary.Resolution.MONTHLY,
            day, _months_later(day, 12),
        ))

    return windows
