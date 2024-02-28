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
        # {site_name: {timestamp: [{data}, ...]}}
        data = airnow_api.query(county, timestamp=timestamp, previous=previous)
        for site_name, container in data.items():
            if 'PM2.5' not in list(container.values())[0]:
                # Skip any monitors that don't have PM2.5 data
                # (Some monitors only report, e.g., ozone.)
                print('[AirNow] Insufficient data:', site_name)
                continue

            # Get the first entry for updating the monitor info.
            entry = list(list(container.values())[0].values())[0]

            # Look up the monitor by name. If it doesn't exist, create it.
            try:
                monitor = AirNow.objects.get(name=site_name)
                print('[AirNow] Monitor exists:', monitor.name)
            except AirNow.DoesNotExist:
                latlon = Point(entry['Longitude'], entry['Latitude'], srid=4326)
                county = County.lookup(latlon)
                if not county:
                    print('[AirNow] Monitor OOB:', site_name)
                    continue

                monitor = AirNow.objects.create(
                    name=site_name,
                    position=latlon,
                    county=county,
                    data_provider=entry.get('AgencyName', ''),
                    location=AirNow.LOCATION.outside
                )
                print('[AirNow] Monitor created:', site_name)

            # This block can be removed at a later date, once
            # existing monitors have been updated with the AgencyName.
            if entry.get('AgencyName') and not monitor.data_provider:
                monitor.data_provider = entry['AgencyName']
                monitor.save()

            for timestamp, data in container.items():
                if data.get('PM2.5') is None:
                    continue

                timestamp = parse_datetime(timestamp)
                try:
                    entry = monitor.entries.get(timestamp=timestamp)
                    entry = monitor.process_entry(entry, data)
                    entry.save()
                    print('\t[AirNow] Entry updated:', timestamp)
                except Entry.DoesNotExist:
                    entry = monitor.create_entry(data)
                    print('\t[AirNow] Entry created:', timestamp)

                monitor.check_latest(entry)
                if monitor.latest_id == entry.pk:
                    monitor.save()
