from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.gis.geos import GEOSGeometry, MultiPolygon
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.timezone import make_aware
from django_huey import db_periodic_task
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
    rows = geodata.gdf_from_url(url, limit_to_region=True)

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
    rows = geodata.gdf_from_url(url, limit_to_region=True)

    with transaction.atomic():
        Fire.objects.filter(date=date).delete()
        for row in rows.itertuples():
            geometry = GEOSGeometry(row.geometry.wkt, srid=4326)
            fire = Fire(
                date=date,
                satellite=row.Satellite,
                timestamp=parse_timestamp(f'{row.YearDay} {row.Time}'),
                frp=row.FRP,
                ecosystem=row.Ecosystem,
                method=row.Method,
                geometry=geometry,
            )
            try:
                fire.full_clean()
                fire.save()
            except ValidationError:
                pass


# Re-fetch the previous day's fire data one final time (~1pm PST).
@db_periodic_task(crontab(minute='0', hour='21'), priority=50)
def fetch_fire_final(date=None):
    if date is None:
        date = timezone.now().astimezone(settings.DEFAULT_TIMEZONE).date() - timedelta(days=1)
    fetch_fire.call_local(date)
