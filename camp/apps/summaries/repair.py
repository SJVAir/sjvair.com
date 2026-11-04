"""
Repair summary rows written with wrong period boundaries (see repair_summaries).

Three steps, in order: fill missing hourly region rows, delete daily-and-longer
rows whose timestamp isn't a Pacific period start, then re-roll everything
above hourly from the rows below. Each step is idempotent and commits per
batch, so an interrupted run is finished by running it again.

A misaligned row is deleted only when the period it stands for is one this
run covers (see `stands_for` and `plan`); the rest are left in place and
reported, so a run never deletes a row it has no replacement plan for.
"""
from collections import defaultdict, namedtuple
from datetime import timedelta

from camp.apps.regions.models import Region
from camp.apps.summaries.backfill import backfill_region_hours
from camp.apps.summaries.models import BaseSummary, MonitorSummary, RegionSummary
from camp.apps.summaries.periods import is_period_start, iter_period_starts, period_end, period_start
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

DELETE_ID_BATCH = 500
DELETE_TIMESTAMP_BATCH = 200
REGION_HOUR_BATCH = 24 * 7
REGION_HOUR_CHUNK = timedelta(days=7)
ROLL_PROGRESS_EVERY = 50


def _batches(items, size):
    items = list(items)
    for i in range(0, len(items), size):
        yield items[i:i + size]


def _noop(message):
    pass


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
        for ws in iter_period_starts(resolution, start, end):
            if period_end(resolution, ws) <= now:
                lo = min(lo, ws)
                hi = max(hi, period_end(resolution, ws))
    return lo, hi


Span = namedtuple('Span', 'resolution start end periods rolled')


def plan(start, end, now):
    """
    {resolution: Span} for a repair of [start, end).

    `periods` are the periods this run covers at that resolution: those
    overlapping repair_range() for days and months, those overlapping
    [start, end) for quarters, seasons and years. Misaligned rows standing for
    one of them are deleted. `rolled` is the finished ones, which are re-rolled;
    an unfinished one is left for its scheduled rollup when it ends.
    """
    wide_start, wide_end = repair_range(start, end, now)
    spans = {}
    for resolution in RESOLUTIONS:
        lo, hi = (start, end) if resolution in COARSE else (wide_start, wide_end)
        periods = list(iter_period_starts(resolution, lo, hi))
        rolled = [p for p in periods if period_end(resolution, p) <= now]
        spans[resolution] = Span(resolution, lo, hi, periods, rolled)
    return spans


def scan_range(spans):
    """The timestamps to scan for misaligned rows: every covered period, plus the day before the first."""
    lo = min(span.periods[0] for span in spans.values())
    hi = max(period_end(span.resolution, span.periods[-1]) for span in spans.values())
    return lo, hi


def stands_for(resolution, ts):
    """
    The start of the period a misaligned row stands for: the period holding
    the hour after its timestamp. That is the next period for a row stamped an
    hour early (23:00 the day before), the period holding it for one stamped an
    hour late (01:00) or mid-period (a season starting May 1).
    """
    return period_start(resolution, ts + timedelta(hours=1))


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


Decision = namedtuple('Decision', 'delete outside windows skipped')


def decide(spans, misaligned):
    """
    What one kind's run does with its misaligned rows, as a Decision:

    - `delete`: {resolution: [timestamps]} standing for a covered period.
    - `outside`: {resolution: [timestamps]} left in place and reported.
    - `windows`: {resolution: [window starts]} to re-roll (finished, covered).
    - `skipped`: {resolution: [period starts]} covered periods dropped because
      re-rolling them would read a row left in place, or a finer period that
      was itself dropped.

    A left-in-place row still sits inside the windows of coarser periods (the
    2026-02-28T23:00-08:00 day row standing for March 1 is inside February), so
    re-rolling those would count it. They are dropped from the run, which
    turns the rows standing for them into left-in-place rows too; this repeats
    until nothing changes. The run then never deletes a row it doesn't
    replace and never re-rolls from a row it left misaligned.
    """
    source_of = dict(ROLLUPS)
    covered = {resolution: set(span.periods) for resolution, span in spans.items()}
    skipped = {resolution: set() for resolution in RESOLUTIONS}

    def split():
        delete, outside = {}, {}
        for resolution, timestamps in misaligned.items():
            for ts in timestamps:
                target = delete if stands_for(resolution, ts) in covered[resolution] else outside
                target.setdefault(resolution, []).append(ts)
        return delete, outside

    while True:
        delete, outside = split()
        changed = False
        for target in RESOLUTIONS:
            source = source_of[target]
            if source == R.HOURLY:
                continue   # hourly rows are never misaligned
            blockers = outside.get(source, []) + sorted(skipped[source])
            for p in sorted(covered[target]):
                end = period_end(target, p)
                if any(p <= ts < end for ts in blockers):
                    covered[target].discard(p)
                    skipped[target].add(p)
                    changed = True
        if not changed:
            break

    windows = {
        resolution: [p for p in span.rolled if p in covered[resolution]]
        for resolution, span in spans.items()
    }
    return Decision(delete, outside, windows, {r: sorted(p) for r, p in skipped.items() if p})


def delete_misaligned(kind, ids, misaligned, dry_run=False, progress=_noop):
    """
    Delete (or with dry_run, count) the given misaligned rows of `ids`: one
    DELETE per resolution, batch of 500 ids and batch of 200 timestamps, each
    committed on its own. Returns {resolution: rows}.
    """
    model, ids_field, _ = KINDS[kind]
    counts = {resolution: 0 for resolution in RESOLUTIONS}
    verb = 'count' if dry_run else 'delete'
    for resolution, timestamps in misaligned.items():
        batches = [
            (id_batch, ts_batch)
            for id_batch in _batches(ids, DELETE_ID_BATCH)
            for ts_batch in _batches(timestamps, DELETE_TIMESTAMP_BATCH)
        ]
        for n, (id_batch, ts_batch) in enumerate(batches, 1):
            qs = model.objects.filter(
                resolution=resolution,
                timestamp__in=ts_batch,
                **{f'{ids_field}__in': id_batch},
            )
            rows = qs.count() if dry_run else qs.delete()[0]
            counts[resolution] += rows
            progress(f'{kind} {resolution} {verb}: batch {n}/{len(batches)} ({rows:,} rows)')
    return counts


def missing_region_hours(region_ids, start, end, progress=_noop):
    """
    Per region, the hours in [start, end) that have an hourly MonitorSummary
    from a monitor inside the region but no hourly RegionSummary, as
    {region_id: [hours]}.

    Each region's monitors are looked up once. The hours are then read a week
    at a time for every region in scope together: one query for the distinct
    (timestamp, monitor) hourly monitor rows in the week and one for the
    distinct (region, timestamp) hourly region rows, both bounded by the
    (resolution, timestamp) range, never a query per hour or per region.
    """
    monitor_sets = {}
    for region in Region.all_objects.filter(pk__in=region_ids, boundary__isnull=False).order_by('pk'):
        monitors = frozenset(region.monitors.values_list('pk', flat=True))
        if monitors:
            monitor_sets[region.pk] = monitors
    if not monitor_sets:
        return {}
    in_scope = frozenset().union(*monitor_sets.values())
    region_pks = list(monitor_sets)

    chunks = []
    chunk_start = start
    while chunk_start < end:
        chunks.append((chunk_start, min(chunk_start + REGION_HOUR_CHUNK, end)))
        chunk_start = chunks[-1][1]

    missing = defaultdict(list)
    for n, (lo, hi) in enumerate(chunks, 1):
        monitors_at = defaultdict(set)
        rows = (
            MonitorSummary.objects
            .filter(resolution=R.HOURLY, timestamp__gte=lo, timestamp__lt=hi)
            .values_list('timestamp', 'monitor_id')
            .distinct()
        )
        for ts, monitor_id in rows:
            if monitor_id in in_scope:
                monitors_at[ts].add(monitor_id)

        have = defaultdict(set)
        rows = (
            RegionSummary.objects
            .filter(resolution=R.HOURLY, timestamp__gte=lo, timestamp__lt=hi, region_id__in=region_pks)
            .values_list('region_id', 'timestamp')
            .distinct()
        )
        for region_id, ts in rows:
            have[region_id].add(ts)

        hours = sorted(monitors_at)
        found = 0
        for region_id, monitors in monitor_sets.items():
            for ts in hours:
                if ts not in have[region_id] and not monitors.isdisjoint(monitors_at[ts]):
                    missing[region_id].append(ts)
                    found += 1
        progress(f'region hour scan: week {n}/{len(chunks)} ({found:,} missing)')
    return dict(missing)


def fill_region_hours(missing, progress=_noop):
    """Compute the missing hourly region rows. Returns the number of rows written."""
    written = 0
    regions = list(Region.all_objects.filter(pk__in=list(missing)).select_related('boundary').order_by('pk'))
    for n, region in enumerate(regions, 1):
        monitor_grades = dict(region.monitors.with_grade().values_list('pk', 'grade'))
        rows = 0
        for hours in _batches(missing[region.pk], REGION_HOUR_BATCH):
            rows += backfill_region_hours(region, hours, monitor_grades)
        written += rows
        progress(
            f'region hour fill: region {n}/{len(regions)} ({region.pk}, {region.name}): '
            f'{len(missing[region.pk]):,} hours, {rows:,} rows'
        )
    return written


def reroll_windows(start, end, now):
    """{resolution: [window starts]} that a repair of [start, end) re-rolls, in re-roll order."""
    return {resolution: span.rolled for resolution, span in plan(start, end, now).items()}


def reroll(kind, ids, start, end, now, windows=None, progress=_noop):
    """Re-roll every resolution above hourly for `ids`. Returns {resolution: windows rolled}."""
    _, _, rollup = KINDS[kind]
    windows = windows or reroll_windows(start, end, now)
    counts = {}
    for target, source in ROLLUPS:
        counts[target] = 0
        if not ids:
            continue
        total = len(windows[target])
        for ws in windows[target]:
            rollup(target, source, ws, period_end(target, ws), **{f'{kind}_ids': ids})
            counts[target] += 1
            if counts[target] % ROLL_PROGRESS_EVERY == 0 or counts[target] == total:
                progress(f'{kind} {target} roll: {counts[target]:,}/{total:,} windows')
    return counts
