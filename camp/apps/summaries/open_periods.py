"""
Open-period rows: monthly, quarterly, seasonal and yearly summaries for
periods the scheduled rollups haven't written yet (the period holding today,
and the previous one until it settles), built on request from the stored
monthly and daily rows plus the open days, and never saved.
"""
import hashlib
from collections import defaultdict
from datetime import datetime, timedelta
from functools import reduce
from operator import or_

from django.core.cache import cache
from django.db.models import Q

from camp.apps.summaries.aggregators import rollup_region_stats, rollup_summaries
from camp.apps.summaries.models import BaseSummary, MonitorSummary, RegionSummary
from camp.apps.summaries.open_days import (
    OPEN_ROWS_CACHE_SECONDS, STATS_COLUMNS, build_open_rows, daily_statistic, open_days,
)
from camp.apps.summaries.peaks import DAILY_FIGURES
from camp.apps.summaries.period_stats import COARSE_RESOLUTIONS, expected_days, period_figure
from camp.apps.summaries.periods import iter_period_starts, period_end, period_start
from camp.apps.summaries.schedule import is_settled

MONTH = BaseSummary.Resolution.MONTHLY.value


def open_periods(resolution: str, now: datetime) -> list[datetime]:
    """
    The period starts of `resolution` that may be open at `now`, the current
    one last: the period holding now, plus the previous one until its plain
    settle margin has passed since it ended (whether a stored row exists is the
    caller's per-series check).
    """
    if resolution not in COARSE_RESOLUTIONS:
        raise ValueError(f'Not a coarse resolution: {resolution}')
    current = period_start(resolution, now)
    if is_settled(resolution, current, now=now):
        return [current]
    return [period_start(resolution, current - timedelta(hours=1)), current]


def _month_runs(starts):
    """[start, end) spans of consecutive months in a set of month starts."""
    runs = []
    for start in sorted(starts):
        if runs and runs[-1][1] == start:
            runs[-1][1] = period_end('month', start)
        else:
            runs.append([start, period_end('month', start)])
    return [tuple(run) for run in runs]


def _exclusions(kind, owner, skipped):
    """
    Q terms (to OR) matching the daily rows of each series in its skipped
    months. Series that skip the same months share a term, so a page of owners
    with the same stored months needs one term per processor set, not one per
    series (a long OR of per-series terms is costly to plan and JIT).
    """
    by_runs = defaultdict(set)  # (processor, runs) -> owners
    for key, starts in skipped.items():
        processor = key[1] if kind == 'monitor' else None
        by_runs[(processor, tuple(_month_runs(starts)))].add(key[0])
    # Processors sharing both the runs and the exact owner set share a term.
    groups = defaultdict(set)  # (runs, owners) -> processors
    for (processor, runs), owners in by_runs.items():
        groups[(runs, frozenset(owners))].add(processor)

    terms = []
    for (runs, owners), processors in groups.items():
        term = Q(**{f'{owner}__in': sorted(owners, key=str)})
        if kind == 'monitor':
            term &= Q(processor__in=sorted(processors))
        term &= reduce(or_, (Q(timestamp__gte=start, timestamp__lt=end) for start, end in runs))
        terms.append(term)
    return terms


def build_open_period_rows(
    kind: str, owner_ids: list, entry_model, resolution: str, now: datetime,
    processor_q: Q | None = None,
) -> dict:
    """
    Unsaved rows of `resolution` (MonitorSummary or RegionSummary) for each
    series of `entry_model` among `owner_ids`, one per open period with data.
    The previous period is left out for a series that has a stored row of
    `resolution` for it.

    Stats roll up, per period: the stored MONTHLY rows inside it (not for
    `month`), the stored DAILY rows of the months those don't cover, and the
    open-day rows of days with no stored DAILY row. The period figure averages
    the daily figures of every stored DAILY row and open-day row in it, against
    the days from the period's start through today. Peaks are null, as on
    stored coarse rows. `processor_q` filters monitor series.

    Returns {owner_id: [rows]} ordered by series then period; owners with no
    rows are absent. Runs one coarse read, one daily stats read, a daily figure read when
    stored months stand in for days, and build_open_rows.
    """
    if kind == 'monitor':
        model, owner = MonitorSummary, 'monitor_id'
        extra = ('processor',)
    elif kind == 'region':
        model, owner = RegionSummary, 'region_id'
        extra = ('weight', 'station_count')
    else:
        raise ValueError(f'Unknown kind: {kind}')

    periods = open_periods(resolution, now)
    today = period_start('day', now)
    span_end = period_end(resolution, periods[-1])
    entry_type = entry_model.entry_type
    statistic = daily_statistic(entry_model)
    figure_columns = (statistic,) if statistic else ()

    base = model.objects.filter(**{f'{owner}__in': owner_ids}, entry_type=entry_type)
    if kind == 'monitor' and processor_q is not None:
        base = base.filter(processor_q)

    def series_key(row):
        if kind == 'monitor':
            return (row[owner], row['processor'])
        return (row[owner],)

    def period_of(ts):
        start = period_start(resolution, ts)
        return start if start in periods else None

    # Stored rows of `resolution` (the previous period's "already written"
    # check) and, coarser than a month, the finished months that stand in for
    # their days. One read either way.
    coarse_resolutions = {resolution, MONTH}
    stored_coarse = set()  # (series, period) with a stored row of `resolution`
    months = defaultdict(list)  # (series, period) -> monthly records
    covered = defaultdict(set)  # series -> month starts with a stored monthly row
    coarse = base.filter(
        resolution__in=coarse_resolutions, timestamp__gte=periods[0], timestamp__lt=span_end,
    ).values(owner, 'timestamp', 'resolution', *STATS_COLUMNS, *extra)
    for row in coarse:
        key = series_key(row)
        if row['resolution'] == resolution:
            if row['timestamp'] in periods:
                stored_coarse.add((key, row['timestamp']))
        elif (period := period_of(row['timestamp'])) is not None:
            months[(key, period)].append(row)
            covered[key].add(row['timestamp'])

    stats_inputs = defaultdict(list)  # (series, period) -> records
    figures = defaultdict(list)  # (series, period) -> non-null daily figures
    stored_days = defaultdict(set)  # series -> day starts with a stored daily row
    for (key, period), rows in months.items():
        stats_inputs[(key, period)].extend(rows)

    # The stats read skips the days a stored monthly row stands in for, so their
    # digests are never fetched. When it skips any, a figure-only read covers
    # every stored daily row (the figures and the stored-day check need them all).
    daily = base.filter(
        resolution=BaseSummary.Resolution.DAILY, timestamp__gte=periods[0], timestamp__lt=span_end,
    )
    # Days the stats read leaves out, per series: covered months, and the whole
    # previous period where its own row is stored (that period is skipped).
    skipped = defaultdict(set)
    for key, starts in covered.items():
        skipped[key] |= starts
    if len(periods) > 1:
        previous_months = set(iter_period_starts('month', periods[0], periods[1]))
        for key, period in stored_coarse:
            if period == periods[0]:
                skipped[key] |= previous_months
    exclusions = _exclusions(kind, owner, skipped)
    figures_apart = bool(statistic and exclusions)
    stats_daily = daily.exclude(reduce(or_, exclusions)) if exclusions else daily
    stats_columns = (*STATS_COLUMNS, *extra, *(() if figures_apart else figure_columns))
    for row in stats_daily.order_by('timestamp').values(owner, 'timestamp', *stats_columns):
        key = series_key(row)
        stored_days[key].add(row['timestamp'])
        period = period_of(row['timestamp'])
        if period is None:
            continue
        stats_inputs[(key, period)].append(row)
        if statistic and not figures_apart and row[statistic] is not None:
            figures[(key, period)].append(row[statistic])

    if figures_apart:
        series_columns = (owner, 'processor') if kind == 'monitor' else (owner,)
        for row in daily.values(*series_columns, 'timestamp', statistic):
            key = series_key(row)
            stored_days[key].add(row['timestamp'])
            period = period_of(row['timestamp'])
            if period is not None and row[statistic] is not None:
                figures[(key, period)].append(row[statistic])

    open_rows = build_open_rows(
        kind, owner_ids, entry_model, now, processor_q=processor_q, with_tdigest=True,
    )
    for rows in open_rows.values():
        for open_row in rows:
            record = {f: getattr(open_row, f) for f in (owner, *STATS_COLUMNS, *extra)}
            key = series_key(record)
            period = period_of(open_row.timestamp)
            if period is None or open_row.timestamp in stored_days[key]:
                continue
            if period_start('month', open_row.timestamp) not in covered[key]:
                stats_inputs[(key, period)].append(record)
            figure = getattr(open_row, statistic) if statistic else None
            if figure is not None:
                figures[(key, period)].append(figure)

    expected = {
        p: expected_days(p, min(period_end(resolution, p), period_end('day', today)))
        for p in periods
    }
    rollup = rollup_summaries if kind == 'monitor' else rollup_region_stats

    result = defaultdict(list)
    keys = sorted({key for key, _ in stats_inputs}, key=lambda k: tuple(str(v) for v in k))
    for key in keys:
        for period in periods:
            if (key, period) in stored_coarse:
                continue
            records = stats_inputs.get((key, period))
            # Open rows are never saved: no merged digest, and p25/p75 come straight
            # from the inputs' centroids (merging digests is the slow part).
            stats = rollup(records, with_tdigest=False, percentiles='centroids') if records else None
            if stats is None:
                continue

            fields = dict(
                entry_type=entry_type, resolution=resolution, timestamp=period,
                **stats, **dict.fromkeys(DAILY_FIGURES),
            )
            if statistic:
                mean, days = period_figure(figures[(key, period)], expected[period])
                fields.update(
                    daily_statistic_mean=mean, daily_statistic_days=days,
                    daily_statistic_expected_days=expected[period],
                )
            if kind == 'monitor':
                row = MonitorSummary(monitor_id=key[0], processor=key[1], **fields)
            else:
                station_count = max(r['station_count'] for r in records)
                row = RegionSummary(region_id=key[0], station_count=station_count, **fields)
            result[key[0]].append(row)
    return dict(result)


def open_period_rows_cache_key(
    kind, owner_ids, entry_model, resolution, now, processor_q=None,
) -> str:
    """
    The cache key for one build_open_period_rows call: kind, resolution, entry
    type, series filter, owner set (order doesn't matter) and the open-period
    set. The open days are hashed in with the periods: they change at midnight
    (one more expected day) and when yesterday settles, inside one period set.
    """
    periods = ','.join(p.isoformat() for p in open_periods(resolution, now))
    days = ','.join(day.isoformat() for day in open_days(now))
    owners = ','.join(sorted(str(pk) for pk in owner_ids))
    series = '' if processor_q is None else str(processor_q)
    digest = hashlib.sha256(f'{series}|{owners}|{periods};{days}'.encode()).hexdigest()
    return f'open_periods:v1:{kind}:{resolution}:{entry_model.entry_type}:{digest}'


def cached_open_period_rows(
    kind: str, owner_ids: list, entry_model, resolution: str, now: datetime,
    processor_q: Q | None = None,
) -> dict:
    """
    build_open_period_rows, shared through the cache for OPEN_ROWS_CACHE_SECONDS,
    as cached_open_rows does (unsaved instances keyed by str(pk); the result is
    keyed by the caller's pks; `processor_q` is keyed by its str()).
    """
    key = open_period_rows_cache_key(kind, owner_ids, entry_model, resolution, now, processor_q)
    cached = cache.get(key)
    if cached is None:
        result = build_open_period_rows(
            kind, owner_ids, entry_model, resolution, now, processor_q=processor_q,
        )
        cache.set(key, {str(pk): rows for pk, rows in result.items()}, OPEN_ROWS_CACHE_SECONDS)
        return result
    return {pk: cached[str(pk)] for pk in owner_ids if str(pk) in cached}
