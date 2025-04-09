from datetime import datetime, timedelta

import esri2gpd
import pytz

from django.conf import settings
from django.contrib.gis.geos import Point
from django.utils import timezone


from django_huey import db_task, db_periodic_task
from huey import crontab

from camp.apps.monitors.models import Entry
from camp.apps.monitors.aqview.models import AQview
from camp.utils.counties import County
from camp.utils.datetime import make_aware

AQVIEW_URL = "https://gis.carb.arb.ca.gov/hosting/rest/services/Hosted/AQview_revised_PROD_view/FeatureServer/0"


@db_periodic_task(crontab(minute='*/15'), priority=50)
def import_aqview_data():
    records = esri2gpd.get(AQVIEW_URL, where=' and '.join([
        "externalmonitorid in ('BAM 1022', 'BAM 1020')",
        "countyname in ({})".format(
            ', '.join([f"'{c}'" for c in County.names])
        ),
    ])).to_dict('records')

    for row in records:
        process_aqview_data.call_local(row)


@db_task(priority=50)
def process_aqview_data(payload):
    if payload['countyname'] not in County.names:
        return False

    # Get or create the monitor
    try:
        monitor = AQview.objects.get(name=payload['sitename'])
    except AQview.DoesNotExist:
        monitor = AQview.objects.create(
            name=payload['sitename'],
            position=Point(payload['geometry'].x, payload['geometry'].y, srid=4326),
            county=payload['countyname'],
            location=AQview.LOCATION.outside,
            device=payload.get('externalmonitorid'),
            data_provider=payload.get('dataprovidername', ''),
            data_provider_url=payload.get('dplink', ''),
        )

    # Calculate the timestamp and make it timezone aware.
    payload['timestamp'] = make_aware(
        datetime.fromtimestamp(payload['maptime'] / 1000) - timedelta(hours=payload['hourindex']),
        pytz.timezone('America/Los_Angeles')
    )

    monitor.create_entries(payload)

    # Legacy
    try:
        entry = monitor.entries.get(timestamp=payload['timestamp'])
        entry = monitor.process_entry(entry, payload)
        entry.save()
        print('\t[AQview] Entry updated:', payload['timestamp'])
    except Entry.DoesNotExist:
        entry = monitor.create_entry_legacy(payload)
        print('\t[AQview] Entry created:', payload['timestamp'])

    monitor.check_latest(entry)
    if monitor.latest_id == entry.pk:
        monitor.save()
