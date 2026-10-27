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
from decimal import Decimal
from functools import reduce

from django.db import transaction
from django.utils import timezone

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


class WindowEntries:
    '''
    One window's stored entries for one entry model, loaded in a single query, and the
    writes the window makes to them, applied together. Looking up each hour on its own
    meant several random reads per row into tables far too big to be cached.
    '''

    def __init__(self, EntryModel, monitors, start, end):
        self.EntryModel = EntryModel
        self.places = Decimal(1).scaleb(-EntryModel._meta.get_field('value').decimal_places)
        self.entries = {}
        for entry in (EntryModel.objects
                .filter(monitor_id__in=[m.pk for m in monitors.values()], timestamp__gte=start, timestamp__lte=end, sensor='')):
            entry.monitor = monitors[entry.monitor_id]  # spares a query when it's cloned
            self.entries[(entry.monitor_id, entry.timestamp, entry.stage, entry.processor)] = entry
        self.created, self.changed, self.removed = {}, {}, {}

    def upsert(self, monitor, timestamp, stage, value, processor='', origin_id=None):
        # As the column stores it, so an unchanged value compares equal.
        value = Decimal(str(value)).quantize(self.places)
        key = (monitor.pk, timestamp, stage, processor)
        entry = self.entries.get(key)
        if entry is None:
            entry = monitor.initialize_entry(self.EntryModel,
                timestamp=timestamp, stage=stage, processor=processor, value=value, origin_id=origin_id)
            self.entries[key] = self.created[key] = entry
        elif entry.value != value or entry.origin_id != origin_id:
            entry.value, entry.origin_id = value, origin_id
            if key not in self.created:
                self.changed[key] = entry
        return entry

    def discard(self, monitor, timestamp, stage, processor=''):
        key = (monitor.pk, timestamp, stage, processor)
        if (entry := self.entries.pop(key, None)) is None:
            return
        self.changed.pop(key, None)
        if self.created.pop(key, None) is None:
            self.removed[key] = entry

    def discard_hour(self, monitor, timestamp, keep_stage):
        '''Drop the hour's entries, except those at `keep_stage`.'''
        for key in [k for k in self.entries if k[:2] == (monitor.pk, timestamp) and k[2] != keep_stage]:
            self.discard(monitor, *key[1:])

    def save(self):
        if self.removed:
            pks = [entry.pk for entry in self.removed.values()]
            LatestEntry.objects.filter(entry_id__in=pks).delete()
            self.EntryModel.objects.filter(pk__in=pks).delete()

        # RAW first: derived entries point at it.
        created = sorted(self.created.values(), key=lambda e: e.stage != self.EntryModel.Stage.RAW)
        self.EntryModel.objects.bulk_create(created, batch_size=1000)

        now = timezone.now()
        for entry in self.changed.values():
            entry.modified = now
        self.EntryModel.objects.bulk_update(self.changed.values(), ['value', 'origin', 'modified'], batch_size=1000)

        # Only each series' newest entry can move LatestEntry.
        newest = {}
        for entry in [*created, *self.changed.values()]:
            series = (entry.monitor_id, entry.stage, entry.processor)
            if series not in newest or entry.timestamp > newest[series].timestamp:
                newest[series] = entry
        for entry in newest.values():
            entry.monitor.update_latest_entry(entry)


def backfill_items(items, geometry, monitors, start, end):
    '''Import one window's payload rows. `monitors` caches lookups by site name.'''
    counts = {'entries': 0, 'missing': 0, 'skipped': 0}
    rows = []
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
        rows.append((item, EntryModel, monitor))

    by_pk = {monitor.pk: monitor for monitor in monitors.values() if monitor is not None}
    windows = {EntryModel: WindowEntries(EntryModel, by_pk, start, end) for EntryModel in {row[1] for row in rows}}

    for item, EntryModel, monitor in rows:
        entries = windows[EntryModel]
        timestamp = AirNow.get_timestamp(item)
        raw = None
        if AirNowNowCast.is_missing(value := AirNow.get_value(item)):
            # A -999 hour stored before missing values were skipped: drop RAW and what was
            # derived from it, but not the NowCast.
            entries.discard_hour(monitor, timestamp, keep_stage=EntryModel.Stage.CALIBRATED)
            counts['missing'] += 1
        else:
            raw = entries.upsert(monitor, timestamp, EntryModel.Stage.RAW, value)
            # Rebuilt in place: the normal pipeline skips an hour that already has them.
            for Processor in monitor.ENTRY_CONFIG[EntryModel].get('processors', {}).get(EntryModel.Stage.RAW, []):
                processor = Processor(raw)
                derived = processor.process() if processor.is_valid() else None
                if derived is None:
                    entries.discard(monitor, timestamp, Processor.next_stage, Processor.name)
                else:
                    entries.upsert(monitor, timestamp, Processor.next_stage, derived.value,
                        processor=Processor.name, origin_id=raw.pk)
            counts['entries'] += 1

        # Saved even when the hour's RAW is missing: AirNow's NowCast only needs 2 of the
        # last 3 hours.
        nowcast = AirNow.NOWCAST_PROCESSORS.get(item['Parameter'])
        if nowcast is not None and not AirNowNowCast.is_missing(item.get('Value')):
            entries.upsert(monitor, timestamp, nowcast.next_stage, item['Value'],
                processor=nowcast.name, origin_id=raw.pk if raw else None)

    for entries in windows.values():
        entries.save()
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
            counts = backfill_items(items, geometry, monitors, win_start, win_end)

        for key, value in counts.items():
            totals[key] += value
        log(f'[{idx}/{len(windows)}] {win_start:%Y-%m-%d %H:00} to {win_end:%Y-%m-%d %H:00} UTC: '
            f'{counts["entries"]} entries, {counts["missing"]} missing (-999), {counts["skipped"]} outside the valley')

    totals['monitors'] = sum(monitor is not None for monitor in monitors.values())
    return totals
