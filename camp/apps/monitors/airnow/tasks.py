from django.contrib.gis.geos import Point
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from huey import crontab
from huey.contrib.djhuey import db_task, db_periodic_task, HUEY

from camp.apps.monitors.models import Entry
from camp.apps.monitors.airnow.models import AirNow
from camp.apps.monitors.airnow.client import airnow_api
from camp.utils.counties import County


@db_periodic_task(crontab(minute='*/15'), priority=50)
def import_airnow_data(timestamp=None, previous=None):
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

            # Look up the monitor by name. If it doesn't exist, create it.
            try:
                monitor = AirNow.objects.get(name=site_name)
                print('[AirNow] Monitor exists:', monitor.name)
            except AirNow.DoesNotExist:
                entry = list(list(container.values())[0].values())[0]
                latlon = Point(entry['Longitude'], entry['Latitude'], srid=4326)
                county = County.lookup(latlon)
                if not county:
                    print('[AirNow] Monitor OOB:', site_name)
                    continue

                monitor = AirNow.objects.create(
                    name=site_name,
                    position=latlon,
                    county=county,
                    location=AirNow.LOCATION.outside
                )
                print('[AirNow] Monitor created:', site_name)

            for timestamp, data in container.items():
                timestamp = parse_datetime(timestamp)
                try:
                    entry = monitor.entries.get(timestamp=timestamp)
                    entry.payload.update(data)
                    print('\t[AirNow] Entry updated:', timestamp)
                except Entry.DoesNotExist:
                    entry = monitor.create_entry(data)
                    print('\t[AirNow] Entry created:', timestamp)

                monitor.process_entry(entry)
                entry.save()
                monitor.check_latest(Entry.objects.get(pk=entry.pk))
