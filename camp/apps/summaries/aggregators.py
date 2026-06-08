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
        for mean, count in d.get('C', []):
            merged.update(mean, count)
    return merged


def _stage_for_processor(processor):
    """Derive entry stage from processor: blank → RAW, non-blank → CALIBRATED."""
    from camp.apps.entries.stages import Stage
    return Stage.RAW if not processor else Stage.CALIBRATED


def compute_stats(values, expected_count):
    """Compute summary stats from a list of float values."""
    if not values:
        return None

    arr = np.array(values)
    count = len(values)
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

    return compute_stats(values, monitor.expected_hourly_entries or 1)


def rollup_summaries(records):
    """
    Aggregate a list of MonitorSummary value dicts into one stats dict.
    Used to roll up hourly → daily → monthly etc.

    Each dict must have: count, expected_count, sum_value, sum_of_squares,
    minimum, maximum, tdigest.

    Returns None if records is empty or total count is zero.
    """
    if not records:
        return None

    count = sum(r['count'] for r in records)
    if count == 0:
        return None

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


def rollup_region_stats(records):
    """
    Aggregate a list of RegionSummary value dicts into one stats dict.

    Like rollup_summaries but uses the exact float `weight` field as the
    variance denominator instead of the rounded integer `count`. This corrects
    the stddev computation when health-score weighting produces fractional
    weights whose rounded sum diverges from the true total.

    Each dict must have: count, weight, expected_count, sum_value,
    sum_of_squares, minimum, maximum, tdigest.

    Returns None if records is empty or total weight is zero.
    """
    if not records:
        return None

    count = sum(r['count'] for r in records)
    weight = sum(r['weight'] for r in records)
    if weight == 0:
        return None

    expected_count = sum(r['expected_count'] for r in records)
    sum_value = sum(r['sum_value'] for r in records)
    sum_of_squares = sum(r['sum_of_squares'] for r in records)
    minimum = min(r['minimum'] for r in records)
    maximum = max(r['maximum'] for r in records)

    mean = sum_value / weight
    variance = max((sum_of_squares / weight) - (mean ** 2), 0)
    stddev = variance ** 0.5

    merged = merge_tdigests([r['tdigest'] for r in records])

    return {
        'count': count,
        'weight': weight,
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
    }


def get_monitor_weight(grade, health_score=None):
    """
    Return the contribution weight for a monitor.

    FEM/FRM monitors always get FEM_WEIGHT (authoritative, no health check needed).
    LCS monitors get LCS_WEIGHT scaled by their health score (0–1 factor).
    Monitors with no health check record get health_factor=1.0.
    """
    from camp.apps.monitors.models import Monitor

    if grade in {Monitor.Grade.FEM, Monitor.Grade.FRM}:
        return FEM_WEIGHT

    health_factor = health_score / MAX_HEALTH_SCORE if health_score is not None else 1.0
    return LCS_WEIGHT * health_factor


def compute_region_summary(region, timestamp, entry_type, monitor_grades=None):
    """
    Compute a weighted region summary from existing hourly MonitorSummary records.

    For each monitor in the region, uses the best available summary: CALIBRATED
    (processor≠'') is preferred over RAW (processor=''). If multiple CALIBRATED
    summaries exist for a monitor, the first alphabetically by processor is used.

    monitor_grades may be pre-supplied as a dict of {monitor_id: grade} to avoid
    the geospatial query (useful when backfilling many hours for the same region).

    Returns a dict ready to use as RegionSummary field values, or None if no
    contributing monitors have a summary for this window.
    """
    from camp.apps.monitors.models import Monitor
    from camp.apps.summaries.models import MonitorSummary, BaseSummary

    if not region.boundary:
        return None

    if monitor_grades is None:
        monitor_grades = dict(
            region.monitors.with_grade().values_list('pk', 'grade')
        )

    monitor_ids = list(monitor_grades)

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

    # Pre-fetch all health checks in one query to avoid N+1 per monitor.
    from camp.apps.qaqc.models import HealthCheck
    health_scores = dict(HealthCheck.objects
        .filter(
            monitor_id__in=[s.monitor_id for s in summaries],
            hour=timestamp
        )
        .values_list('monitor_id', 'score')
    )

    # Weight by per-monitor mean, not per-observation count. A FEM reporting
    # once per hour and an LCS reporting 30 times per hour should each
    # contribute one weighted vote, not 1 vs 30 votes.
    total_weight = 0.0
    weighted_sum = 0.0
    weighted_sum_sq = 0.0
    minimum = None
    maximum = None
    tdigests = []
    station_count = 0

    for s in summaries:
        if s.count == 0:
            continue
        weight = get_monitor_weight(monitor_grades.get(s.monitor_id), health_scores.get(s.monitor_id))
        if weight == 0:
            continue

        second_moment = s.sum_of_squares / s.count
        total_weight += weight
        weighted_sum += weight * s.mean
        weighted_sum_sq += weight * second_moment
        minimum = s.minimum if minimum is None else min(minimum, s.minimum)
        maximum = s.maximum if maximum is None else max(maximum, s.maximum)
        tdigests.append(s.tdigest)
        station_count += 1

    if station_count == 0 or total_weight == 0:
        return None

    mean = weighted_sum / total_weight
    variance = max(weighted_sum_sq / total_weight - mean ** 2, 0)
    stddev = variance ** 0.5
    merged = merge_tdigests(tdigests)

    return {
        'count': int(round(total_weight)),
        'expected_count': int(round(total_weight)),
        'weight': total_weight,
        'sum_value': weighted_sum,
        'sum_of_squares': weighted_sum_sq,
        'minimum': minimum,
        'maximum': maximum,
        'mean': mean,
        'stddev': stddev,
        'p25': merged.percentile(25),
        'p75': merged.percentile(75),
        'tdigest': tdigest_to_dict(merged),
        'station_count': station_count,
    }
