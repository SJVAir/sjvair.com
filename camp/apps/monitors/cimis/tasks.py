from django.contrib.gis.geos import Point

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
