from collections.abc import Callable
from datetime import datetime, timedelta, timezone as dt_timezone

from django.utils import timezone
from huey import crontab

from camp.apps.summaries.periods import period_end
from camp.utils.datetime import localtime

# Huey crontabs run in UTC. A Pacific hour lands on one of two UTC hours
# depending on DST, so pacific_crontab() matches both and keeps the one that
# is the Pacific hour. Keys are the Pacific hour, values the UTC hours that
# contain it in PDT and PST.
ROLLUP_UTC_HOURS = {1: '8,9', 2: '9,10'}


def is_pacific_hour(hour, now=None):
    """
    True when `now` falls in the given Pacific hour. The repeated hour on
    the fall-back day counts once (fold 0 only).
    """
    local = localtime(now or timezone.now())
    return local.hour == hour and local.fold == 0


def pacific_crontab(hour: int, minute: str, **crontab_kwargs) -> Callable[[datetime], bool]:
    """
    A Huey periodic-task schedule for a Pacific wall-clock hour. Huey's
    scheduler calls it with the minute it is scheduling (naive UTC under
    Huey's utc=True default), so the Pacific-hour decision is made when the
    task is enqueued, not when a worker gets to it: a run that starts late
    still runs. Other crontab fields (`day`, `month`, ...) are UTC, which is
    the same date as Pacific at these early-morning hours.
    """
    matches = crontab(hour=ROLLUP_UTC_HOURS[hour], minute=minute, **crontab_kwargs)

    def validate(timestamp):
        if timezone.is_naive(timestamp):
            timestamp = timestamp.replace(tzinfo=dt_timezone.utc)
        timestamp = timestamp.astimezone(dt_timezone.utc)
        return matches(timestamp.replace(tzinfo=None)) and is_pacific_hour(hour, timestamp)

    return validate


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


def is_settled(resolution, range_end, now=None):
    """
    True when every period in a range ending at `range_end` (exclusive) has
    had time to finish its rollups. An open range (None) is never settled.
    """
    if range_end is None:
        return False
    last_period_end = period_end(resolution, range_end - timedelta(microseconds=1))
    return (now or timezone.now()) >= last_period_end + SETTLE_MARGIN[resolution]


# The minute of each hour the hourly parent tasks are scheduled for
# (crontab minutes in camp/apps/summaries/tasks.py).
HOURLY_FIRE_MINUTE = {'monitor': 45, 'region': 50}

# A parent that starts this long after its scheduled minute logs a warning.
LATE_RUN_WARNING = timedelta(minutes=10)


def hour_for_run(fire_minute: int, now: datetime | None = None) -> tuple[datetime, timedelta]:
    """
    The hour an hourly parent should summarize, and how late it started.

    The hour comes from the schedule, not from when a worker picked the task
    up: `fire` is the latest HH:`fire_minute` (UTC) at or before `now`, and
    the hour is the one before the hour holding `fire`. A parent that waited
    behind other work therefore still summarizes the hour it was scheduled for.
    Returns (hour, lateness), lateness being `now - fire`.

    That holds only up to 60 minutes late. A parent that starts 60+ minutes
    after its fire time resolves to the next fire instead: it summarizes the
    next hour (which that fire's own run summarizes again), the hour it was
    scheduled for gets no row, and no late-run warning names it, since the
    lateness it reports is measured from the next fire. The daily
    check_summary_integrity reports the missing region hours the next day.
    """
    now = (now or timezone.now()).astimezone(dt_timezone.utc)
    fire = now.replace(minute=fire_minute, second=0, microsecond=0)
    if fire > now:
        fire -= timedelta(hours=1)
    return fire.replace(minute=0) - timedelta(hours=1), now - fire
