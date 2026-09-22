import time

from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.gis.geos import GEOSGeometry, MultiPolygon
from django.core.exceptions import ValidationError  # used by fetch_smoke
from django.db import transaction
from django.utils import timezone
from django.utils.timezone import make_aware
import requests
from django_huey import db_periodic_task, db_task
from huey import crontab

from camp.utils import geodata

from .models import Fire, Smoke

SMOKE_BASE_URL = 'https://satepsanone.nesdis.noaa.gov/pub/FIRE/web/HMS/Smoke_Polygons/Shapefile'
FIRE_BASE_URL = 'https://satepsanone.nesdis.noaa.gov/pub/FIRE/web/HMS/Fire_Points/Shapefile'


def parse_timestamp(string):
    return make_aware(datetime.strptime(string, '%Y%j %H%M'), timezone=ZoneInfo(settings.TIME_ZONE))


# NOAA data is available from ~8am to ~3am PST the following day.
@db_periodic_task(crontab(minute='0', hour='0-3,15-23'), priority=50)
def fetch_smoke(date=None):
    if date is None:
        date = timezone.now().astimezone(settings.DEFAULT_TIMEZONE).date()

    url = f'{SMOKE_BASE_URL}/{date.year}/{date.strftime("%m")}/hms_smoke{date.strftime("%Y%m%d")}.zip'
    # Plumes are large regional polygons, so keep any that touch the region
    # rather than requiring half their area to fall inside it. NOAA revises
    # the file under the same URL through the day, so never reuse the cache.
    rows = geodata.gdf_from_url(url, limit_to_region=True, threshold=0.0, cache=False)

    with transaction.atomic():
        Smoke.objects.filter(date=date).delete()
        for row in rows.itertuples():
            geometry = GEOSGeometry(row.geometry.wkt, srid=4326)
            if geometry.geom_type == 'Polygon':
                geometry = MultiPolygon(geometry)
            smoke = Smoke(
                date=date,
                satellite=row.Satellite,
                start=parse_timestamp(row.Start),
                end=parse_timestamp(row.End),
                density=row.Density.lower().strip(),
                geometry=geometry,
            )
            try:
                smoke.full_clean()
                smoke.save()
            except ValidationError:
                pass


# Re-fetch the previous day's smoke data one final time (~1pm PST).
@db_periodic_task(crontab(minute='0', hour='21'), priority=50)
def fetch_smoke_final(date=None):
    if date is None:
        date = timezone.now().astimezone(settings.DEFAULT_TIMEZONE).date() - timedelta(days=1)
    fetch_smoke.call_local(date)


# NOAA data is available from ~8am to ~3am PST the following day.
@db_periodic_task(crontab(minute='0', hour='0-3,15-23'), priority=50)
def fetch_fire(date=None):
    if date is None:
        date = timezone.now().astimezone(settings.DEFAULT_TIMEZONE).date()

    url = f'{FIRE_BASE_URL}/{date.year}/{date.strftime("%m")}/hms_fire{date.strftime("%Y%m%d")}.zip'
    # NOAA revises the file under the same URL through the day, so never reuse the cache.
    rows = geodata.gdf_from_url(url, limit_to_region=True, cache=False)

    with transaction.atomic():
        Fire.objects.filter(date=date).delete()
        for row in rows.itertuples():
            geometry = GEOSGeometry(row.geometry.wkt, srid=4326)
            fire = Fire(
                date=date,
                satellite=row.Satellite,
                timestamp=parse_timestamp(f'{row.YearDay} {row.Time}'),
                frp=Decimal(f'{row.FRP:.3f}') if row.FRP >= 0 else None,
                ecosystem=row.Ecosystem,
                method=row.Method,
                geometry=geometry,
            )
            fire.save()


# Re-fetch the previous day's fire data one final time (~1pm PST).
@db_periodic_task(crontab(minute='0', hour='21'), priority=50)
def fetch_fire_final(date=None):
    if date is None:
        date = timezone.now().astimezone(settings.DEFAULT_TIMEZONE).date() - timedelta(days=1)
    fetch_fire.call_local(date)


@db_task(queue='secondary')
def import_hms_range(start, end, smoke=True, fire=True, delay=0.5):
    """
    Sequentially import HMS smoke and/or fire for every date in [start, end],
    pausing ``delay`` seconds between downloads so we don't hammer NOAA.
    Dates whose file is missing from the archive are skipped and reported.
    """
    if start > end:
        start, end = end, start

    tasks = []
    if smoke:
        tasks.append(('smoke', fetch_smoke))
    if fire:
        tasks.append(('fire', fetch_fire))

    skipped = []
    first = True
    date = start
    while date <= end:
        for name, task in tasks:
            if not first:
                time.sleep(delay)
            first = False
            try:
                task.call_local(date)
            except requests.HTTPError as err:
                if err.response is not None and err.response.status_code == 404:
                    skipped.append(f'{name} {date}')
                    continue
                raise
        date += timedelta(days=1)

    return {'start': start, 'end': end, 'skipped': skipped}
