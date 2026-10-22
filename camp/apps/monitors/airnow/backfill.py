"""
Re-import historical AirNow data for every parameter the regular import
requests (PM2.5, PM10, ozone, CO, NO2, SO2).

Each hour's RAW entry is upserted -- from RawConcentration for PM2.5, PM10,
and ozone, whose NowCast is also stored as CALIBRATED (see AirNow.handle_payload). Entries derived from RAW
by the per-entry pipeline (CLEANED PM2.5) are rebuilt in place: the normal
pipeline skips an hour that already has one, so a re-import would otherwise
leave values derived from the old NowCast-based RAW.
"""

import time
from datetime import timedelta, timezone as dt_timezone
from functools import reduce

from django.db import transaction

from camp.apps.calibrations.core.processors.airnow import AirNowNowCast
from camp.apps.monitors.airnow.api import airnow_api
from camp.apps.monitors.airnow.models import AirNow
from camp.apps.monitors.airnow.tasks import get_or_create_monitor
from camp.apps.monitors.models import LatestEntry
from camp.apps.regions.models import Region

# AirNow rejects a request over its (undocumented) record limit, between
# roughly 13.7k and 17k rows. Valley-wide, all parameters, 4 days is ~13.7k
# today; 3 leaves headroom for periods with more sites. A window that still
# exceeds it is split in half and retried.
WINDOW = timedelta(days=3)
RECORD_LIMIT_ERROR = 'exceeds the record query limit'

# AirNow allows 500 requests an hour; this keeps a run under 450.
PAUSE_SECONDS = 8


def get_windows(start, end, window=WINDOW):
    '''Splits [start, end) into windows of inclusive UTC hours, as AirNow expects.'''
    start = start.astimezone(dt_timezone.utc).replace(minute=0, second=0, microsecond=0)
    end = end.astimezone(dt_timezone.utc)

    windows = []
    current = start
    while current < end:
        window_end = min(current + window, end)
        windows.append((current, window_end - timedelta(hours=1)))
        current = window_end
    return windows


class AirNowError(Exception):
    pass


def fetch_window(bbox, start, end, pause):
    '''Fetch [start, end] (inclusive hours), halving the window while it exceeds the record limit.'''
    items = airnow_api.fetch_entries(bbox=bbox, start_date=start, end_date=end)
    time.sleep(pause)
    if isinstance(items, list):
        return items

    # An error comes back as {'WebServiceError': [{'Message': ...}]}.
    message = ' '.join(error.get('Message', '') for error in items.get('WebServiceError', [])) or str(items)
    hours = int((end - start) / timedelta(hours=1)) + 1
    if RECORD_LIMIT_ERROR not in message or hours < 2:
        raise AirNowError(message)

    split = start + timedelta(hours=hours // 2)
    return (fetch_window(bbox, start, split - timedelta(hours=1), pause)
            + fetch_window(bbox, split, end, pause))


def rebuild_derived_entries(monitor, raw):
    '''Recompute the pipeline's entries derived from `raw`, updating existing ones in place.'''
    config = monitor.ENTRY_CONFIG.get(raw.__class__, {})
    for Processor in config.get('processors', {}).get(raw.stage, []):
        EntryModel = Processor.entry_model
        existing = EntryModel.objects.filter(
            monitor_id=monitor.pk,
            timestamp=raw.timestamp,
            sensor=raw.sensor,
            stage=Processor.next_stage,
            processor=Processor.name,
        ).first()

        processor = Processor(raw)
        derived = processor.process() if processor.is_valid() else None

        if derived is None:
            if existing is not None:
                LatestEntry.objects.filter(entry_id=existing.pk).delete()
                existing.delete()
        elif existing is None:
            derived.save()
            monitor.update_latest_entry(derived)
        elif existing.value != derived.value:
            existing.value = derived.value
            existing.origin_id = raw.pk
            existing.save()


def remove_missing_entries(monitor, EntryModel, timestamp):
    '''Drop a -999 hour stored before missing values were skipped: RAW and its derived entries (not the NowCast).'''
    stale = (EntryModel.objects
        .filter(monitor_id=monitor.pk, timestamp=timestamp, sensor='')
        .exclude(stage=EntryModel.Stage.CALIBRATED))
    LatestEntry.objects.filter(entry_id__in=list(stale.values_list('pk', flat=True))).delete()
    stale.delete()


def backfill_items(items, geometry, monitors):
    '''Import one window's payload rows. `monitors` caches lookups by site name.'''
    counts = {'entries': 0, 'missing': 0, 'skipped': 0}
    for item in items:
        EntryModel = AirNow.ENTRY_MAP.get(item['Parameter'])
        if EntryModel is None:
            continue

        name = item['SiteName']
        if name not in monitors:
            monitors[name] = get_or_create_monitor(item, geometry)
        if (monitor := monitors[name]) is None:
            counts['skipped'] += 1
            continue

        monitor.handle_payload(item)
        timestamp = AirNow.get_timestamp(item)
        if AirNowNowCast.is_missing(AirNow.get_value(item)):
            remove_missing_entries(monitor, EntryModel, timestamp)
            counts['missing'] += 1
            continue

        raw = EntryModel.objects.filter(
            monitor_id=monitor.pk,
            timestamp=timestamp,
            sensor='',
            stage=EntryModel.Stage.RAW,
        ).first()
        if raw is not None:
            rebuild_derived_entries(monitor, raw)
        counts['entries'] += 1

    return counts


def backfill_airnow(start, end, pause=PAUSE_SECONDS, log=None):
    log = log or (lambda msg: None)

    boundaries = [county.boundary.geometry for county in Region.objects.counties().select_related('boundary')]
    if not boundaries:
        raise ValueError('No county regions are loaded; run import_counties first.')
    geometry = reduce(lambda a, b: a.union(b), boundaries)

    windows = get_windows(start, end)
    monitors = {}
    totals = {'entries': 0, 'missing': 0, 'skipped': 0}
    for idx, (win_start, win_end) in enumerate(windows, start=1):
        items = fetch_window(geometry.extent, win_start, win_end, pause)
        with transaction.atomic():
            counts = backfill_items(items, geometry, monitors)

        for key, value in counts.items():
            totals[key] += value
        log(f'[{idx}/{len(windows)}] {win_start:%Y-%m-%d %H:00} to {win_end:%Y-%m-%d %H:00} UTC: '
            f'{counts["entries"]} entries, {counts["missing"]} missing (-999), {counts["skipped"]} outside the valley')

    totals['monitors'] = sum(monitor is not None for monitor in monitors.values())
    return totals
