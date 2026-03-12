from datetime import timedelta

import numpy as np
from tdigest import TDigest


# Weight constants for region summary weighting
FEM_WEIGHT = 3.0
LCS_WEIGHT = 1.0
MAX_HEALTH_SCORE = 3


def tdigest_to_dict(digest: TDigest) -> dict:
    """Serialize a TDigest to a JSON-safe dict."""
    return {
        'C': [[c.mean, c.count] for c in digest.C.values()],
        'n': digest.n,
    }


def tdigest_from_dict(data: dict) -> TDigest:
    """Deserialize a TDigest from a dict produced by tdigest_to_dict."""
    d = TDigest()
    for mean, count in data.get('C', []):
        d.update(mean, count)
    return d


def merge_tdigests(dicts: list) -> TDigest:
    """Merge a list of serialized TDigest dicts into one TDigest."""
    merged = TDigest()
    for d in dicts:
        merged = merged + tdigest_from_dict(d)
    return merged


def _stage_for_processor(processor):
    """Derive entry stage from processor: blank → RAW, non-blank → CALIBRATED."""
    from camp.apps.entries.stages import Stage
    return Stage.RAW if not processor else Stage.CALIBRATED


def compute_monitor_summary(monitor, timestamp, EntryModel, processor):
    """
    Compute summary stats for one monitor over one hour from raw entries.

    Stage is derived from processor: blank processor → RAW, non-blank → CALIBRATED.

    Returns a dict ready to use as MonitorSummary field values, or None if
    there are no entries in the window.
    """
    hour_end = timestamp + timedelta(hours=1)
    stage = _stage_for_processor(processor)

    values = [
        float(v)
        for v in EntryModel.objects.filter(
            monitor=monitor,
            timestamp__gte=timestamp,
            timestamp__lt=hour_end,
            stage=stage,
            processor=processor,
        ).values_list('value', flat=True)
        if v is not None
    ]

    if not values:
        return None

    arr = np.array(values)
    count = len(values)
    expected_count = monitor.expected_hourly_entries or 1
    sum_value = float(arr.sum())
    sum_of_squares = float((arr ** 2).sum())
    mean = float(arr.mean())
    stddev = float(arr.std())

    digest = TDigest()
    digest.batch_update(arr.tolist())

    return {
        'count': count,
        'expected_count': expected_count,
        'sum_value': sum_value,
        'sum_of_squares': sum_of_squares,
        'minimum': float(arr.min()),
        'maximum': float(arr.max()),
        'mean': mean,
        'stddev': stddev,
        'p25': float(np.percentile(arr, 25)),
        'p75': float(np.percentile(arr, 75)),
        'tdigest': tdigest_to_dict(digest),
        'is_complete': count >= 0.8 * expected_count,
    }


def rollup_summaries(queryset):
    """
    Aggregate a queryset of MonitorSummary or RegionSummary records into one
    stats dict. Used to roll up hourly → daily → monthly etc.

    Returns None if the queryset is empty.
    """
    records = list(queryset.values(
        'count', 'expected_count', 'sum_value',
        'sum_of_squares', 'minimum', 'maximum', 'tdigest',
    ))

    if not records:
        return None

    count = sum(r['count'] for r in records)
    expected_count = sum(r['expected_count'] for r in records)
    sum_value = sum(r['sum_value'] for r in records)
    sum_of_squares = sum(r['sum_of_squares'] for r in records)
    minimum = min(r['minimum'] for r in records)
    maximum = max(r['maximum'] for r in records)

    mean = sum_value / count
    variance = max((sum_of_squares / count) - (mean ** 2), 0)
    stddev = variance ** 0.5

    merged = merge_tdigests([r['tdigest'] for r in records])

    return {
        'count': count,
        'expected_count': expected_count,
        'sum_value': sum_value,
        'sum_of_squares': sum_of_squares,
        'minimum': minimum,
        'maximum': maximum,
        'mean': mean,
        'stddev': stddev,
        'p25': merged.percentile(25),
        'p75': merged.percentile(75),
        'tdigest': tdigest_to_dict(merged),
        'is_complete': count >= 0.8 * expected_count,
    }


def get_monitor_weight(monitor, hour):
    """
    Return the contribution weight for a monitor at a given hour.

    FEM/FRM monitors always get FEM_WEIGHT (authoritative, no health check needed).
    LCS monitors get LCS_WEIGHT scaled by their health score (0–1 factor).
    Monitors with no health check record get health_factor=1.0.
    """
    from camp.apps.monitors.models import Monitor
    from camp.apps.qaqc.models import HealthCheck

    if monitor.grade in {Monitor.Grade.FEM, Monitor.Grade.FRM}:
        return FEM_WEIGHT

    try:
        health = HealthCheck.objects.get(monitor=monitor, hour=hour)
        health_factor = health.score / MAX_HEALTH_SCORE
    except HealthCheck.DoesNotExist:
        health_factor = 1.0

    return LCS_WEIGHT * health_factor


def compute_region_summary(region, timestamp, entry_type):
    """
    Compute a weighted region summary from existing hourly MonitorSummary records.

    For each monitor in the region, uses the best available summary: CALIBRATED
    (processor≠'') is preferred over RAW (processor=''). If multiple CALIBRATED
    summaries exist for a monitor, the first alphabetically by processor is used.

    Returns a dict ready to use as RegionSummary field values, or None if no
    contributing monitors have a summary for this window.
    """
    from camp.apps.monitors.models import Monitor
    from camp.apps.summaries.models import MonitorSummary, BaseSummary

    if not region.boundary:
        return None

    monitor_ids = list(
        Monitor.objects
        .filter(position__within=region.boundary.geometry)
        .values_list('pk', flat=True)
    )

    if not monitor_ids:
        return None

    # For each monitor, prefer CALIBRATED (processor≠'') over RAW (processor='').
    # Order by processor so '' (RAW) sorts before any calibrated processor name,
    # meaning later entries override earlier ones — last write wins per monitor_id.
    all_summaries = (
        MonitorSummary.objects
        .filter(
            monitor_id__in=monitor_ids,
            timestamp=timestamp,
            resolution=BaseSummary.Resolution.HOURLY,
            entry_type=entry_type,
        )
        .select_related('monitor')
        .order_by('processor')  # '' < any non-blank string
    )

    # One summary per monitor: CALIBRATED overrides RAW
    best_by_monitor = {}
    for s in all_summaries:
        existing = best_by_monitor.get(s.monitor_id)
        if existing is None or (existing.processor == '' and s.processor != ''):
            best_by_monitor[s.monitor_id] = s

    summaries = list(best_by_monitor.values())

    if not summaries:
        return None

    weighted_count = 0.0
    weighted_expected = 0.0
    weighted_sum = 0.0
    weighted_sum_sq = 0.0
    minimum = None
    maximum = None
    tdigests = []
    station_count = 0

    for s in summaries:
        weight = get_monitor_weight(s.monitor, timestamp)
        if weight == 0:
            continue

        weighted_count += weight * s.count
        weighted_expected += weight * s.expected_count
        weighted_sum += weight * s.sum_value
        weighted_sum_sq += weight * s.sum_of_squares
        minimum = s.minimum if minimum is None else min(minimum, s.minimum)
        maximum = s.maximum if maximum is None else max(maximum, s.maximum)
        tdigests.append(s.tdigest)
        station_count += 1

    if station_count == 0 or weighted_count == 0:
        return None

    mean = weighted_sum / weighted_count
    variance = max((weighted_sum_sq / weighted_count) - (mean ** 2), 0)
    stddev = variance ** 0.5
    merged = merge_tdigests(tdigests)

    return {
        'count': int(round(weighted_count)),
        'expected_count': int(round(weighted_expected)),
        'sum_value': weighted_sum,
        'sum_of_squares': weighted_sum_sq,
        'minimum': minimum,
        'maximum': maximum,
        'mean': mean,
        'stddev': stddev,
        'p25': merged.percentile(25),
        'p75': merged.percentile(75),
        'tdigest': tdigest_to_dict(merged),
        'is_complete': weighted_count >= 0.8 * weighted_expected,
        'station_count': station_count,
    }
