"""
Import historical AQview PM2.5 from CARB's download tool
(https://aqview.arb.ca.gov/continuous-monitoring-data): hourly CSVs, or
the zips the tool downloads with one inside.

MeasurementStartTime is the start of the hour in PST all year (no DST),
unlike the live feed's `maptime`. Each file's range replaces what's stored
for each of its monitors: entries the live import wrote before its
timestamps were fixed sit at the wrong hours, often off the hour, so they
wouldn't be overwritten by an upsert.
"""

import csv
import io
import zipfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal, InvalidOperation

from django.contrib.gis.geos import Point
from django.db import transaction

from camp.apps.entries import models as entry_models
from camp.apps.monitors.aqview.models import AQview
from camp.apps.monitors.models import LatestEntry
from camp.apps.regions.counties import COUNTY_NAMES

PST = dt_timezone(timedelta(hours=-8))
PM25_PARAMETER_ID = '88101'
DEVICES = {'BAM 1022', 'BAM 1020'}
INVALID_FLAG = 'Invalid'
BATCH_SIZE = 5000


def read_files(path):
    '''Yield (name, rows) for a download-tool CSV, or for each CSV in a zip, one file at a time.'''
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            for name in sorted(archive.namelist()):
                if name.lower().endswith('.csv'):
                    with archive.open(name) as handle:
                        yield name, csv.DictReader(io.TextIOWrapper(handle, encoding='utf-8-sig'))
        return

    with open(path, encoding='utf-8-sig', newline='') as handle:
        yield path, csv.DictReader(handle)


def parse_timestamp(value):
    return datetime.fromisoformat(value).replace(tzinfo=PST).astimezone(dt_timezone.utc)


def parse_value(row):
    # AdjustedValue is the provider's correction, when there is one.
    raw = row.get('AdjustedValue') or row.get('MeasuredValue')
    try:
        return Decimal(raw)
    except (InvalidOperation, TypeError):
        return None


def is_relevant(row):
    return (
        row.get('ParameterId') == PM25_PARAMETER_ID
        and row.get('MonitorId') in DEVICES
        and row.get('County') in COUNTY_NAMES
    )


def get_or_create_monitor(row):
    try:
        return AQview.objects.get(name=row['Site'])
    except AQview.DoesNotExist:
        return AQview.objects.create(
            name=row['Site'],
            position=Point(float(row['Longitude']), float(row['Latitude']), srid=4326),
            location=AQview.LOCATION.outside,
            device=row['MonitorId'],
            data_provider=row.get('DataProvider', ''),
        )


def group_by_site(rows):
    '''
    {site: (first row, {timestamp: (value, invalidated)})} for the relevant rows. Keeps only
    what the import needs, since a download can be a million rows. A repeated hour keeps the
    last row.
    '''
    sites = {}
    for row in rows:
        if not is_relevant(row):
            continue
        first, hours = sites.setdefault(row['Site'], (row, {}))
        hours[parse_timestamp(row['MeasurementStartTime'])] = (parse_value(row), row.get('DataProviderFlag') == INVALID_FLAG)
    return sites


def split_by_month(hours):
    '''
    Split {timestamp: ...} into month-sized pieces as (start, end, hours), end exclusive.
    Each piece runs up to the next one's first hour, so together they replace the whole
    span the file covers, gaps included.
    '''
    months = defaultdict(dict)
    for timestamp, value in hours.items():
        months[(timestamp.year, timestamp.month)][timestamp] = value

    pieces = [months[key] for key in sorted(months)]
    starts = [min(piece) for piece in pieces]
    ends = starts[1:] + [max(hours) + timedelta(hours=1)]
    return list(zip(starts, ends, pieces))


def replace_monitor_range(monitor, start, end, hours):
    '''Replace the monitor's PM2.5 entries in [start, end) with the hours' valid rows. Returns counts.'''
    PM25 = entry_models.PM25
    Cleaner = monitor.ENTRY_CONFIG[PM25]['processors'][PM25.Stage.RAW][0]

    stale = PM25.objects.filter(monitor_id=monitor.pk, timestamp__gte=start, timestamp__lt=end)
    LatestEntry.objects.filter(monitor_id=monitor.pk, entry_id__in=list(stale.values_list('pk', flat=True))).delete()
    removed = stale.delete()[0]

    raws, cleaned, invalid = [], [], 0
    for timestamp, (value, invalidated) in sorted(hours.items()):
        if invalidated or value is None:
            invalid += 1
            continue

        raw = monitor.initialize_entry(PM25, timestamp=timestamp, value=value)
        raws.append(raw)
        processor = Cleaner(raw)
        if processor.is_valid() and (derived := processor.process()) is not None:
            cleaned.append(derived)

    PM25.objects.bulk_create(raws, batch_size=BATCH_SIZE)
    PM25.objects.bulk_create(cleaned, batch_size=BATCH_SIZE)
    for entries in (raws, cleaned):
        if entries:
            monitor.update_latest_entry(max(entries, key=lambda e: e.timestamp))

    return {'raw': len(raws), 'cleaned': len(cleaned), 'invalid': invalid, 'removed': removed}


def import_aqview_history(paths, log=None):
    log = log or (lambda msg: None)
    totals = defaultdict(int)
    for path in paths:
        for name, rows in read_files(path):
            sites = group_by_site(rows)
            if not sites:
                log(f'{name}: no AQview PM2.5 rows for the valley')
                continue

            for site, (first, hours) in sorted(sites.items()):
                monitor = get_or_create_monitor(first)
                counts = defaultdict(int)
                # A month at a time keeps memory and each transaction small.
                for start, end, month in split_by_month(hours):
                    with transaction.atomic():
                        for key, value in replace_monitor_range(monitor, start, end, month).items():
                            counts[key] += value

                for key, value in counts.items():
                    totals[key] += value
                totals['monitors'] += 1
                log(f'{name}: {site.strip()} {min(hours):%Y-%m-%d %H:00} to {max(hours):%Y-%m-%d %H:00} UTC: '
                    f'{counts["raw"]} raw, {counts["cleaned"]} cleaned, {counts["invalid"]} invalidated, '
                    f'{counts["removed"]} old entries removed')

    return dict(totals)
