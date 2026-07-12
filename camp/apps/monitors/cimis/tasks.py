from datetime import timedelta

from django.conf import settings
from django.contrib.gis.geos import Point
from django.utils import timezone

from django_huey import db_task, db_periodic_task
from huey import crontab

from camp.apps.monitors.cimis.api import CIMISAPI
from camp.apps.monitors.cimis.models import CIMIS
from camp.utils.counties import County


def parse_hms_coordinate(value):
    if not value or '/' not in value:
        return None
    try:
        return float(value.split('/')[1].strip())
    except (ValueError, IndexError):
        return None


@db_periodic_task(crontab(hour='3', minute='0'), priority=50)
def discover_cimis_stations():
    if settings.CIMIS_API_KEY is None:
        # Do nothing if we don't have a key.
        return

    api = CIMISAPI()
    for station in api.get_stations():
        process_cimis_station.call_local(station)


@db_task(priority=50)
def process_cimis_station(station):
    county = station.get('County')
    if county not in County.names:
        return False

    if station.get('IsActive') != 'True':
        return False

    latitude = parse_hms_coordinate(station.get('HmsLatitude'))
    longitude = parse_hms_coordinate(station.get('HmsLongitude'))
    if latitude is None or longitude is None:
        return False

    monitor, _created = CIMIS.objects.get_or_create(
        station_number=station['StationNbr'],
        defaults={
            'name': f"CIMIS #{station['StationNbr']} - {station.get('Name', '')}",
            'position': Point(longitude, latitude, srid=4326),
            'location': CIMIS.LOCATION.outside,
        },
    )
    return monitor


def _ingest_cimis_data(target_date):
    station_numbers = list(CIMIS.objects.values_list('station_number', flat=True))
    if not station_numbers:
        return

    api = CIMISAPI()
    providers = api.get_hourly_data(
        station_numbers=station_numbers,
        start_date=target_date,
        end_date=target_date,
        data_items=list(CIMIS.ENTRY_MAP.keys()),
    )

    for provider in providers:
        for record in provider.get('Records', []):
            process_cimis_data.call_local(record)


@db_periodic_task(crontab(minute='45'), priority=50)
def import_cimis_data():
    today = timezone.localtime(timezone.now()).date()
    _ingest_cimis_data(today)


@db_periodic_task(crontab(hour='4', minute='0'), priority=50)
def finalize_cimis_data():
    """
    CIMIS applies QC to hourly data with some lag, so late hours from
    yesterday (especially the 2400 boundary hour) can still be missing
    or unfinalized by the time today's calendar date rolls over and
    import_cimis_data stops re-querying them. This re-pulls yesterday's
    full day once, after CIMIS's typical QC window has closed, to catch
    anything that was missed. Safe to re-run: entries are deduplicated
    on (monitor, timestamp, sensor, stage, processor).
    """
    yesterday = timezone.localtime(timezone.now()).date() - timedelta(days=1)
    _ingest_cimis_data(yesterday)


@db_task(priority=50)
def process_cimis_data(record):
    try:
        monitor = CIMIS.objects.get(station_number=record['Station'])
    except CIMIS.DoesNotExist:
        return False

    return monitor.handle_payload(record)
