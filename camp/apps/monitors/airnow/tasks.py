from django.conf import settings
from django.contrib.gis.geos import Point
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from django_huey import db_task, db_periodic_task
from huey import crontab

from camp.apps.monitors.models import Entry
from camp.apps.monitors.airnow.models import AirNow
from camp.apps.monitors.airnow.client import airnow_api
from camp.utils.counties import County


@db_periodic_task(crontab(minute='*/15'), priority=50)
def import_airnow_data(timestamp=None, previous=None):
    if settings.AIRNOW_API_KEY is None:
        # Do nothing if we don't have a key.
        return

    timestamp = timestamp or timezone.now()
    previous = previous or 1

    for county in County.names:
        data = airnow_api.query_ng(county, timestamp=timestamp, previous=previous)
        for item in data:

            # Look up the monitor by name. If it doesn't exist, create it.
            try:
                monitor = AirNow.objects.get(name=item['SiteName'])
            except AirNow.DoesNotExist:
                latlon = Point(item['Longitude'], item['Latitude'], srid=4326)
                county = County.lookup(latlon)
                if not county:
                    continue

                monitor = AirNow.objects.create(
                    name=item['SiteName'],
                    position=latlon,
                    county=county,
                    data_provider=item.get('AgencyName', ''),
                    location=AirNow.LOCATION.outside
                )

            if entry := monitor.handle_payload(item):
                cleaned = monitor.process_entry_ng(entry)
                print('\t[AirNow] Entry created:', entry.timestamp)


@db_periodic_task(crontab(minute='*/15'), priority=50)
def import_airnow_data_legacy(timestamp=None, previous=None):
    if settings.AIRNOW_API_KEY is None:
        # Do nothing if we don't have a key.
        return

    timestamp = timestamp or timezone.now()
    previous = previous or 1

    for county in County.names:
        # {site_name: {timestamp: [{data}, ...]}}
        data = airnow_api.query(county, timestamp=timestamp, previous=previous)
        for site_name, container in data.items():
            # Get the first entry for updating the monitor info.
            entry = list(list(container.values())[0].values())[0]

            # Look up the monitor by name. If it doesn't exist, create it.
            try:
                monitor = AirNow.objects.get(name=site_name)
            except AirNow.DoesNotExist:
                latlon = Point(entry['Longitude'], entry['Latitude'], srid=4326)
                county = County.lookup(latlon)
                if not county:
                    continue

                monitor = AirNow.objects.create(
                    name=site_name,
                    position=latlon,
                    county=county,
                    data_provider=entry.get('AgencyName', ''),
                    location=AirNow.LOCATION.outside
                )

            for timestamp, data in container.items():
                timestamp = parse_datetime(timestamp)
                try:
                    entry = monitor.entries.get(timestamp=timestamp)
                    entry = monitor.process_entry(entry, data)
                    entry.save()
                except Entry.DoesNotExist:
                    entry = monitor.create_entry_legacy(data)

                monitor.check_latest(entry)
                if monitor.latest_id == entry.pk:
                    monitor.save()
