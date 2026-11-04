"""
Repair summary rows written with wrong period boundaries (see repair_summaries).

Three steps, in order: fill missing hourly region rows, delete daily-and-longer
rows whose timestamp isn't a Pacific period start, then re-roll everything
above hourly from the rows below. Each step is idempotent and commits per
batch, so an interrupted run is finished by running it again.
"""
from collections import defaultdict
from datetime import timedelta

from camp.apps.regions.models import Region
from camp.apps.summaries.backfill import backfill_region_hours
from camp.apps.summaries.models import BaseSummary, MonitorSummary, RegionSummary
from camp.apps.summaries.periods import is_period_start, iter_period_starts, period_end
from camp.apps.summaries.tasks import rollup_monitor_summaries, rollup_region_summaries

R = BaseSummary.Resolution

# target, source, in re-roll order
ROLLUPS = [
    (R.DAILY, R.HOURLY),
    (R.MONTHLY, R.DAILY),
    (R.QUARTERLY, R.MONTHLY),
    (R.SEASONAL, R.MONTHLY),
    (R.YEARLY, R.MONTHLY),
]
RESOLUTIONS = [target for target, _ in ROLLUPS]
COARSE = [R.QUARTERLY, R.SEASONAL, R.YEARLY]

KINDS = {
    'monitor': (MonitorSummary, 'monitor_id', rollup_monitor_summaries),
    'region': (RegionSummary, 'region_id', rollup_region_summaries),
}

DELETE_BATCH = 500
REGION_HOUR_BATCH = 24 * 7


def _batches(items, size):
    items = list(items)
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _finished_windows(resolution, start, end, now):
    return [
        ws for ws in iter_period_starts(resolution, start, end)
        if period_end(resolution, ws) <= now
    ]


def repair_range(start, end, now):
    """
    The range whose day and month rows a repair of [start, end) touches.

    Re-rolling a month, quarter, season or year reads every row below it in
    that period, so the period's finer rows must be clean too, including any
    that fall outside [start, end). This widens [start, end) to the finished
    month-and-longer periods that overlap it (one step only: periods that
    overlap just the widened part are not re-rolled, so it doesn't chain back
    through the years via the Dec-Feb seasons).
    """
    lo, hi = start, end
    for resolution in [R.MONTHLY, *COARSE]:
        for ws in _finished_windows(resolution, start, end, now):
            lo = min(lo, ws)
            hi = max(hi, period_end(resolution, ws))
    return lo, hi


def find_misaligned(model, ids_field, ids, start, end):
    """
    Daily-and-longer rows in [start - 1 day, end) whose timestamp isn't a
    Pacific period start, as {resolution: [timestamps]}. The extra day catches
    a period that starts at `start` but was stamped an hour early.

    `ids=None` scans every row; an empty list scans nothing.
    """
    if ids is not None and not ids:
        return {}
    qs = model.objects.filter(
        resolution__in=RESOLUTIONS,
        timestamp__gte=start - timedelta(days=1),
        timestamp__lt=end,
    )
    if ids is not None:
        qs = qs.filter(**{f'{ids_field}__in': ids})

    found = defaultdict(list)
    for resolution, ts in qs.values_list('resolution', 'timestamp').distinct().order_by('resolution', 'timestamp'):
        if not is_period_start(resolution, ts):
            found[resolution].append(ts)
    return dict(found)


def delete_misaligned(kind, ids, misaligned, dry_run=False):
    """
    Delete (or with dry_run, count) the misaligned rows of `ids`: one DELETE
    per resolution and batch of 500 ids. Returns {resolution: rows}.
    """
    model, ids_field, _ = KINDS[kind]
    counts = {resolution: 0 for resolution in RESOLUTIONS}
    for resolution, timestamps in misaligned.items():
        for batch in _batches(ids, DELETE_BATCH):
            qs = model.objects.filter(
                resolution=resolution,
                timestamp__in=timestamps,
                **{f'{ids_field}__in': batch},
            )
            if dry_run:
                counts[resolution] += qs.count()
            else:
                counts[resolution] += qs.delete()[0]
    return counts


def missing_region_hours(region_ids, start, end):
    """
    Per region, the hours in [start, end) that have an hourly MonitorSummary
    from a monitor inside the region but no hourly RegionSummary, as
    {region_id: [hours]}. Three queries per region, none per hour.
    """
    missing = {}
    for region in Region.all_objects.filter(pk__in=region_ids, boundary__isnull=False).order_by('pk'):
        monitor_ids = list(region.monitors.values_list('pk', flat=True))
        if not monitor_ids:
            continue
        monitor_hours = set(
            MonitorSummary.objects
            .filter(resolution=R.HOURLY, timestamp__gte=start, timestamp__lt=end, monitor_id__in=monitor_ids)
            .values_list('timestamp', flat=True)
            .distinct()
        )
        if not monitor_hours:
            continue
        region_hours = set(
            RegionSummary.objects
            .filter(region_id=region.pk, resolution=R.HOURLY, timestamp__gte=start, timestamp__lt=end)
            .values_list('timestamp', flat=True)
            .distinct()
        )
        hours = sorted(monitor_hours - region_hours)
        if hours:
            missing[region.pk] = hours
    return missing


def fill_region_hours(missing):
    """Compute the missing hourly region rows. Returns the number of rows written."""
    written = 0
    for region in Region.all_objects.filter(pk__in=list(missing)).select_related('boundary'):
        monitor_grades = dict(region.monitors.with_grade().values_list('pk', 'grade'))
        for hours in _batches(missing[region.pk], REGION_HOUR_BATCH):
            written += backfill_region_hours(region, hours, monitor_grades)
    return written


def reroll_windows(start, end, now):
    """
    {resolution: [window starts]} that a repair of [start, end) re-rolls, in
    re-roll order. Only finished periods. Quarters, seasons and years are the
    ones overlapping [start, end); days and months cover repair_range(), since
    the coarser periods read them.
    """
    wide_start, wide_end = repair_range(start, end, now)
    windows = {}
    for resolution in RESOLUTIONS:
        if resolution in COARSE:
            windows[resolution] = _finished_windows(resolution, start, end, now)
        else:
            windows[resolution] = _finished_windows(resolution, wide_start, wide_end, now)
    return windows


def reroll(kind, ids, start, end, now, windows=None):
    """Re-roll every resolution above hourly for `ids`. Returns {resolution: windows rolled}."""
    _, _, rollup = KINDS[kind]
    windows = windows or reroll_windows(start, end, now)
    counts = {}
    for target, source in ROLLUPS:
        counts[target] = 0
        if not ids:
            continue
        for ws in windows[target]:
            rollup(target, source, ws, period_end(target, ws), **{f'{kind}_ids': ids})
            counts[target] += 1
    return counts
