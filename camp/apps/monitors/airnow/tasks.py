from datetime import timedelta

from django.conf import settings
from django.contrib.gis.geos import Point
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from django_huey import db_task, db_periodic_task
from huey import crontab

from camp.apps.monitors.models import Entry
from camp.apps.monitors.airnow.models import AirNow
from camp.apps.monitors.airnow.client import airnow_api
from camp.apps.regions.models import Region
from camp.utils import gis


@db_periodic_task(crontab(minute='*/15'), priority=50)
def import_airnow_data(start_date=None, end_date=None):
    if settings.AIRNOW_API_KEY is None:
        # Do nothing if we don't have a key.
        return

    end_date = end_date or timezone.now()

    for county in Region.objects.counties().select_related('boundary'):
        if start_date is None:
            oldest_last_entry = (AirNow.objects
                .get_active()
                .filter(position__within=county.boundary.geometry)
                .with_last_entry_timestamp()
                .order_by('last_entry_timestamp')
                .values_list('last_entry_timestamp', flat=True)
                .first()
            )

            # Default window: last 24 hours
            start_date = end_date - timedelta(hours=24)

            if oldest_last_entry:
                # Don't fetch earlier than 24h ago
                start_date = max(oldest_last_entry, start_date)

            # Ensure at least 1h difference
            if start_date > end_date - timedelta(hours=1):
                start_date = end_date - timedelta(hours=1)

        data = airnow_api.query(
            bbox=county.boundary.geometry.extent,
            start_date=start_date,
            end_date=end_date,
        )
        for item in data:
            try:
                # Look up the monitor by name...
                monitor = AirNow.objects.get(name=item['SiteName'])
            except AirNow.DoesNotExist:
                # ...but it doesn't exist, so create it...
                latlon = Point(item['Longitude'], item['Latitude'], srid=gis.EPSG_LATLON)
                if not county.boundary.geometry.contains(latlon):
                    # ...unless it's outside the county!
                    continue

                monitor = AirNow.objects.create(
                    name=item['SiteName'],
                    position=latlon,
                    county=' '.join(county.name.split()[:-1]),
                    data_provider=item.get('AgencyName', ''),
                    location=AirNow.LOCATION.outside
                )

            if entry := monitor.handle_payload(item):
                cleaned = monitor.process_entry_ng(entry)

    legacy_previous = 1
    if start_date:
        legacy_previous = int((end_date - start_date).total_seconds() / 3600)
    import_airnow_data_legacy(timestamp=end_date, previous=legacy_previous)


# @db_periodic_task(crontab(minute='*/15'), priority=50)
def import_airnow_data_legacy(timestamp=None, previous=None):
    if settings.AIRNOW_API_KEY is None:
        # Do nothing if we don't have a key.
        return

    timestamp = timestamp or timezone.now()
    previous = previous or 1

    for county in Region.objects.counties().select_related('boundary'):
        # {site_name: {timestamp: [{data}, ...]}}
        county_name = ' '.join(county.name.split()[:-1])
        data = airnow_api.query_legacy(
            bbox=county.boundary.geometry.extent,
            timestamp=timestamp,
            previous=previous
        )
        for site_name, container in data.items():
            # Get the first entry for updating the monitor info.
            entry = list(list(container.values())[0].values())[0]

            # Look up the monitor by name. If it doesn't exist, create it.
            try:
                monitor = AirNow.objects.get(name=site_name)
            except AirNow.DoesNotExist:
                latlon = Point(entry['Longitude'], entry['Latitude'], srid=4326)
                if not county.boundary.geometry.contains(latlon):
                    continue

                monitor = AirNow.objects.create(
                    name=site_name,
                    position=latlon,
                    county=county_name,
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
