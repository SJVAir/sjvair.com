'''
Window selection, dedupe and estimates for the PurpleAir history import
(PurpleAirHistoryJob). See
docs/superpowers/specs/2026-10-22-purpleair-history-import-design.md.
'''
import math

from datetime import timedelta

from django.db.models import Max, Q

from camp.apps.monitors.legacy_backfill import chunk_start_for
from camp.apps.monitors.purpleair.api import PurpleAirAPI
from camp.apps.monitors.purpleair.models import PurpleAir

# PurpleAir reports every 2 minutes (PurpleAir.EXPECTED_INTERVAL).
EXPECTED_ROW_SECONDS = 120
FIELDS_PER_ROW = len(PurpleAirAPI.HISTORY_FIELDS)


def monitors_for_window(window_start, window_end, monitor_ids=None):
    '''
    Returns pks of the PurpleAir monitors worth requesting for the window:
    those with a sensor_id whose latest entry isn't older than the window
    (a sensor that stopped reporting before it has nothing to fetch). A
    monitor with no latest entries at all is always included.
    '''
    queryset = (PurpleAir.objects
        .filter(sensor_id__isnull=False)
        .annotate(last_entry_at=Max('latest_entries__timestamp'))
        .filter(Q(last_entry_at__isnull=True) | Q(last_entry_at__gte=window_start))
    )
    if monitor_ids:
        queryset = queryset.filter(pk__in=monitor_ids)
    return list(queryset.order_by('pk').values_list('pk', flat=True))


def iter_windows(range_start, range_end, chunk_days):
    '''
    Yields (window_start, window_end), newest first, the way the job walks
    its cursor back from range_end.
    '''
    cursor = range_end
    while cursor > range_start:
        window_start = chunk_start_for(cursor, range_start, chunk_days)
        yield window_start, cursor
        cursor = window_start


def estimate(range_start, range_end, chunk_days, monitor_ids=None):
    '''
    Returns (windows, requests, data_points) for a dry run: one request per
    monitor per window, each expecting a row every 2 minutes with every field.
    '''
    windows = requests = data_points = 0
    for window_start, window_end in iter_windows(range_start, range_end, chunk_days):
        monitors = len(monitors_for_window(window_start, window_end, monitor_ids))
        rows = math.ceil((window_end - window_start).total_seconds() / EXPECTED_ROW_SECONDS)
        windows += 1
        requests += monitors
        data_points += monitors * rows * FIELDS_PER_ROW
    return windows, requests, data_points


def existing_raw_timestamps(monitor, entry_model, window_start, window_end, pad):
    '''
    Existing RAW (sensor -> sorted timestamps) for the window padded by `pad`,
    loaded once so near-duplicates can be checked without a query per entry.
    '''
    existing = {}
    for timestamp, sensor in entry_model.objects.filter(
        monitor=monitor,
        stage=entry_model.Stage.RAW,
        timestamp__gte=window_start - pad,
        timestamp__lte=window_end + pad,
    ).values_list('timestamp', 'sensor'):
        existing.setdefault(sensor, []).append(timestamp)
    for timestamps in existing.values():
        timestamps.sort()
    return existing
