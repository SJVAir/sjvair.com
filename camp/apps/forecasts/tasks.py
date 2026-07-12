import logging
import re
from datetime import datetime, timedelta, timezone as dt_timezone

import requests
from defusedxml import ElementTree as ET

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from django_huey import db_periodic_task
from huey import crontab

from camp.apps.regions.models import Region
from camp.utils.aqi import aqi_label

from .models import Forecast

logger = logging.getLogger(__name__)


FEED_URL = 'https://ww2.valleyair.org/aqinfo/airstatus.xml'

# Both the burnStatus: and AQI: prefixes resolve to this same namespace URI in
# the feed, so <burnStatus:today> and <AQI:today> share one Clark-notation tag.
# See split_today_tomorrow() below for how they're told apart.
NAMESPACE_URI = 'https://ww2.valleyair.org/'

# Maps the feed's raw <county> label to the matching county Region's name.
# "Sequoia National Park and Forest" has no matching Region and is skipped.
ZONE_TO_REGION_NAME = {
    'San Joaquin': 'San Joaquin County',
    'Stanislaus': 'Stanislaus County',
    'Merced': 'Merced County',
    'Madera': 'Madera County',
    'Fresno': 'Fresno County',
    'Kings': 'Kings County',
    'Tulare': 'Tulare County',
    'Kern (SJV Air Basin portion)': 'Kern County',
}

# "101 Unhealthy for Sensitive Groups (O3)" -> value=101, pollutant='O3'
AQI_TEXT_RE = re.compile(r'^(\d+)\s+.+?\(([^)]+)\)$')


def parse_feed_datetime(value):
    """Parses feed timestamps like '2026-07-11T14:31:09 -7:00' into aware datetimes."""
    dt_part, offset_part = value.rsplit(' ', 1)
    sign = -1 if offset_part.startswith('-') else 1
    hours_str, minutes_str = offset_part.lstrip('+-').split(':')
    offset = timedelta(hours=int(hours_str), minutes=int(minutes_str)) * sign
    naive = datetime.strptime(dt_part, '%Y-%m-%dT%H:%M:%S')
    return naive.replace(tzinfo=dt_timezone(offset))


def parse_alert_date(value):
    """Parses an air-alert start/end date attribute. Format hasn't been observed
    live (no sample pull has had an active alert); falls back to None on any
    unexpected format rather than breaking ingestion for every zone."""
    if not value:
        return None
    try:
        return datetime.strptime(value, '%Y-%m-%d').date()
    except ValueError:
        return None


def parse_aqi_text(text):
    match = AQI_TEXT_RE.match((text or '').strip())
    if not match:
        raise ValueError(f'Unrecognized AQI text: {text!r}')
    return int(match.group(1)), match.group(2)


def split_today_tomorrow(elements):
    """Splits the two same-tag elements for a horizon into (burn_status_el, aqi_el).
    They're told apart by content shape: AQI text matches AQI_TEXT_RE, burn status
    text does not. See the namespace-collision note in tasks.py's module docstring."""
    aqi_el = next(el for el in elements if AQI_TEXT_RE.match((el.text or '').strip()))
    burn_el = next(el for el in elements if el is not aqi_el)
    return burn_el, aqi_el


@db_periodic_task(crontab(minute='45', hour='23,0,1,2'), priority=50)
def fetch_forecasts():
    issued_date = timezone.now().astimezone(settings.DEFAULT_TIMEZONE).date()

    response = requests.get(FEED_URL, timeout=30)
    response.raise_for_status()
    root = ET.fromstring(response.content)

    with transaction.atomic():
        Forecast.objects.filter(issued_date=issued_date).delete()
        for item in root.iter('item'):
            zone_name = (item.findtext('county') or '').strip()
            region_name = ZONE_TO_REGION_NAME.get(zone_name)
            if region_name is None:
                continue  # unmapped zone (e.g. Sequoia National Park and Forest)

            region = Region.objects.counties().filter(name=region_name).first()
            if region is None:
                continue  # region not yet imported

            try:
                published_at = parse_feed_datetime(item.findtext('pubdate'))

                alert_el = item.find('airAlertStatus')
                air_alert = alert_el.get('status') == 'YES'
                air_alert_start = parse_alert_date(alert_el.get('startDate'))
                air_alert_end = parse_alert_date(alert_el.get('endDate'))

                for horizon in ('today', 'tomorrow'):
                    elements = item.findall(f'{{{NAMESPACE_URI}}}{horizon}')
                    burn_el, aqi_el = split_today_tomorrow(elements)

                    aqi_value, pollutant = parse_aqi_text(aqi_el.text)
                    forecast_date = parse_feed_datetime(aqi_el.get('date')).date()

                    Forecast.objects.create(
                        region=region,
                        zone_name=zone_name,
                        forecast_date=forecast_date,
                        issued_date=issued_date,
                        published_at=published_at,
                        aqi_value=aqi_value,
                        aqi_category=aqi_label(aqi_value),
                        pollutant=pollutant,
                        burn_status=burn_el.get('status', ''),
                        burn_status_text=burn_el.text or '',
                        air_alert=air_alert,
                        air_alert_start=air_alert_start,
                        air_alert_end=air_alert_end,
                    )
            except (StopIteration, ValueError, AttributeError) as exc:
                # A single zone with an unexpected feed shape (e.g. "Unavailable"
                # AQI text, or a missing pubdate/airAlertStatus element) shouldn't
                # roll back the whole run. Skip it and keep processing the rest.
                logger.warning(
                    'Skipping malformed forecast feed item for zone %r: %s',
                    zone_name, exc,
                )
                continue
