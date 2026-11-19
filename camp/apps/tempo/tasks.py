from datetime import datetime, timedelta

import requests
import sentry_sdk

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone
from django_huey import db_periodic_task
from huey import crontab
from constance import config as constance_config

from camp.utils.datetime import localtime

from .models import Granule
from .sync import sync_granule

PRODUCTS = [choice[0] for choice in Granule.Product.choices]


def sync_granules(timestamps):
    '''
    Syncs every product for each timestamp, reporting individual failures to
    Sentry and moving on.

    A 401 (an expired or revoked Earthdata token) fails every remaining
    request the same way, so it stops the run after one report instead of one
    per product-hour. A 403 can be one collection only (e.g. a new version
    whose EULA hasn't been accepted), so it drops just that product for the
    rest of the run, also reported once.
    '''
    forbidden = set()
    for timestamp in timestamps:
        for product in PRODUCTS:
            if product in forbidden:
                continue
            try:
                sync_granule(product, timestamp)
            except requests.HTTPError as exc:
                sentry_sdk.capture_exception(exc)
                status = getattr(exc.response, 'status_code', None)
                if status == 401:
                    return
                if status == 403:
                    forbidden.add(product)
            except Exception as exc:
                sentry_sdk.capture_exception(exc)


# TEMPO only observes during PT daylight hours; run hourly, 15 min past the
# hour to give NASA's NRT pipeline (~180 min claimed latency, but the top of
# the hour is safest to avoid) a head start. 13-23 UTC covers roughly
# 5am-3pm PT. Since NRT data isn't available for ~180 min, target the hour
# 3 hours back rather than the current hour, which can't possibly have data
# yet.
@db_periodic_task(crontab(minute='15', hour='13-23'), priority=50)
def fetch_tempo():
    timestamp = (timezone.now() - timedelta(hours=3)).replace(minute=0, second=0, microsecond=0)
    sync_granules([timestamp])


# Re-check every hour of yesterday once NASA's standard product typically
# lands (~1pm PT, mirroring camp/apps/hms/tasks.py's fetch_smoke_final).
# "Yesterday" and the hour boundaries below are computed in LA time
# (settings.DEFAULT_TIMEZONE), not UTC -- this is a calendar-day concept,
# and the project's convention is to always reason about dates in LA time.
@db_periodic_task(crontab(minute='0', hour='21'), priority=50)
def fetch_tempo_final():
    yesterday = (localtime() - timedelta(days=1)).date()
    day_start = datetime.combine(yesterday, datetime.min.time(), tzinfo=settings.DEFAULT_TIMEZONE)
    sync_granules(day_start + timedelta(hours=hour) for hour in range(24))


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
    hours = int((end - start) / timedelta(hours=1))
    sync_granules(start + timedelta(hours=hour) for hour in range(hours))


@db_periodic_task(crontab(day_of_week='1', hour='9', minute='0'), priority=30)
def check_earthdata_token_expiry():
    expires_at = constance_config.EARTHDATA_TOKEN_EXPIRES_AT
    if expires_at == settings.EARTHDATA_TOKEN_NOT_SET:
        return  # renewal command has never been run; nothing to warn about yet

    days_left = (localtime(expires_at).date() - localtime().date()).days
    if days_left <= 10:
        send_mail(
            subject=f'TEMPO Earthdata token expires in {days_left} day{"s" if days_left != 1 else ""}',
            message=(
                'Run `heroku run python manage.py renew_earthdata_token` to renew it. '
                'TEMPO ingestion will silently stop working once it expires.'
            ),
            from_email=settings.SERVER_EMAIL,
            recipient_list=settings.TEMPO_ALERT_EMAILS,
        )
