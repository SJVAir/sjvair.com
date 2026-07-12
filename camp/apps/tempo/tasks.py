from datetime import datetime, timedelta

import sentry_sdk

from django.conf import settings
from django.utils import timezone
from django_huey import db_periodic_task
from huey import crontab

from camp.utils.datetime import localtime

from .models import Granule
from .sync import sync_granule

PRODUCTS = [choice[0] for choice in Granule.Product.choices]


# TEMPO only observes during PT daylight hours; run hourly, 15 min past the
# hour to give NASA's NRT pipeline (~180 min claimed latency, but the top of
# the hour is safest to avoid) a head start. 13-23 UTC covers roughly
# 5am-3pm PT. Since NRT data isn't available for ~180 min, target the hour
# 3 hours back rather than the current hour, which can't possibly have data
# yet.
@db_periodic_task(crontab(minute='15', hour='13-23'), priority=50)
def fetch_tempo():
    timestamp = (timezone.now() - timedelta(hours=3)).replace(minute=0, second=0, microsecond=0)
    for product in PRODUCTS:
        try:
            sync_granule(product, timestamp)
        except Exception as exc:
            sentry_sdk.capture_exception(exc)


# Re-check every hour of yesterday once NASA's standard product typically
# lands (~1pm PT, mirroring camp/apps/hms/tasks.py's fetch_smoke_final).
# "Yesterday" and the hour boundaries below are computed in LA time
# (settings.DEFAULT_TIMEZONE), not UTC -- this is a calendar-day concept,
# and the project's convention is to always reason about dates in LA time.
@db_periodic_task(crontab(minute='0', hour='21'), priority=50)
def fetch_tempo_final():
    yesterday = (localtime() - timedelta(days=1)).date()
    day_start = datetime.combine(yesterday, datetime.min.time(), tzinfo=settings.DEFAULT_TIMEZONE)
    for hour in range(24):
        timestamp = day_start + timedelta(hours=hour)
        for product in PRODUCTS:
            try:
                sync_granule(product, timestamp)
            except Exception as exc:
                sentry_sdk.capture_exception(exc)


# Re-syncs a rolling 90-day window weekly to pick up NASA's non-chronological
# V03->V04 reprocessing. sync_granule() is cheap even when nothing has
# changed: find_granule() resolves the current best-available version via a
# lightweight CMR search and sync_granule() compares it against what's
# stored *before* deciding whether to download anything, so most of this
# 90-day window is a no-op check, not a Harmony fetch.
@db_periodic_task(crontab(day_of_week='0', hour='4', minute='0'), priority=30)
def sync_tempo_reprocessing():
    end = timezone.now().replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(days=90)
    timestamp = start
    while timestamp < end:
        for product in PRODUCTS:
            try:
                sync_granule(product, timestamp)
            except Exception as exc:
                sentry_sdk.capture_exception(exc)
        timestamp += timedelta(hours=1)
