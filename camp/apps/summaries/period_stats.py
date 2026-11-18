import math
from bisect import bisect_left
from collections import Counter, defaultdict
from datetime import datetime

from django.db import transaction

from camp.apps.summaries.models import BaseSummary, MonitorSummary, RegionSummary
from camp.apps.summaries.peaks import _owner_group_size, _series_key, peak_entry_models
from camp.apps.summaries.periods import iter_period_starts, period_end

COARSE_RESOLUTIONS = ('month', 'quarter', 'season', 'year')
PERIOD_FIELDS = ('daily_statistic_mean', 'daily_statistic_days', 'daily_statistic_expected_days')


def expected_days(period_start: datetime, until: datetime) -> int:
    """Pacific calendar days in [period_start, until); `until` is a day start."""
    return sum(1 for _ in iter_period_starts('day', period_start, until))


def period_figure(figures: list[float], expected: int) -> tuple[float | None, int]:
    """(mean, days): the mean of the daily figures, only with 75% of the expected days."""
    days = len(figures)
    if expected <= 0 or days < math.ceil(0.75 * expected):
        return None, days
    return float(sum(figures) / days), days


def fill_period_statistics(
    kind: str, ids: list | None, start: datetime, end: datetime, *,
    resolutions=COARSE_RESOLUTIONS, entry_models: list | None = None,
    dry_run: bool = False, batch_size: int = 1000, progress=None,
) -> dict[str, int]:
    """
    Write the average of the daily figures on coarse rows (`resolutions`) with
    `start <= timestamp < end` of the peak entry types (or the given subset).
    `kind` is 'monitor' or 'region'; `ids=None` means all. Only rows whose
    values change are written. Returns the rows updated (or that would be) per
    entry type.
    """
    if kind == 'monitor':
        model, owner = MonitorSummary, 'monitor_id'
    elif kind == 'region':
        model, owner = RegionSummary, 'region_id'
    else:
        raise ValueError(f'Unknown kind: {kind}')

    peaks = peak_entry_models()
    if entry_models is not None:
        peaks = {m: stat for m, stat in peaks.items() if m in entry_models}
    by_type = {m.entry_type: stat for m, stat in peaks.items()}
    resolutions = list(resolutions)
    if not by_type or not resolutions:
        return {}

    coarse = model.objects.filter(
        resolution__in=resolutions,
        timestamp__gte=start,
        timestamp__lt=end,
        entry_type__in=list(by_type),
    )
    if ids is not None:
        coarse = coarse.filter(**{f'{owner}__in': ids})

    owner_ids = list(coarse.order_by(owner).values_list(owner, flat=True).distinct())
    owner_field = owner.removesuffix('_id')
    columns = ['id', owner_field, 'entry_type', 'timestamp', 'resolution', *PERIOD_FIELDS]
    if kind == 'monitor':
        columns.append('processor')

    counts = Counter()
    pending = []

    def flush():
        if not pending:
            return
        if not dry_run:
            with transaction.atomic():
                model.objects.bulk_update(pending, PERIOD_FIELDS, batch_size=batch_size)
        if progress is not None:
            progress(f'{kind} periods: {len(pending)} rows {"would be " if dry_run else ""}updated')
        pending.clear()

    if not owner_ids:
        return {}
    stamps = list(coarse.values_list('timestamp', 'resolution').distinct())
    group_size = _owner_group_size(
        min(t for t, _ in stamps), max(period_end(r, t) for t, r in stamps))

    for i in range(0, len(owner_ids), group_size):
        group = owner_ids[i:i + group_size]
        rows = list(coarse.filter(**{f'{owner}__in': group}).only(*columns))
        figures = _daily_figures(model, owner, group, rows, by_type, kind)

        for row in rows:
            until = period_end(row.resolution, row.timestamp)
            key = _series_key(kind, getattr(row, owner), row.entry_type, getattr(row, 'processor', None))
            series = figures.get(key, ([], []))
            times, values = series
            lo_i = bisect_left(times, row.timestamp)
            hi_i = bisect_left(times, until)
            expected = expected_days(row.timestamp, until)
            mean, days = period_figure(values[lo_i:hi_i], expected)
            new = (mean, days, expected)
            if tuple(getattr(row, f) for f in PERIOD_FIELDS) != new:
                for field, value in zip(PERIOD_FIELDS, new):
                    setattr(row, field, value)
                counts[row.entry_type] += 1
                pending.append(row)
                if len(pending) >= batch_size:
                    flush()

    flush()
    return dict(counts)


def _daily_figures(model, owner, owner_ids, rows, by_type, kind):
    """One read of a group's DAILY rows covering its coarse rows' periods: per series,
    parallel sorted lists of timestamps and non-null figures."""
    if not rows:
        return {}
    first = min(r.timestamp for r in rows)
    last = max(period_end(r.resolution, r.timestamp) for r in rows)
    stats = sorted(set(by_type.values()))
    keys = [owner, 'entry_type', 'timestamp', *stats]
    if kind == 'monitor':
        keys.insert(2, 'processor')
    qs = model.objects.filter(
        **{f'{owner}__in': owner_ids},
        resolution=BaseSummary.Resolution.DAILY,
        entry_type__in={r.entry_type for r in rows},
        timestamp__gte=first,
        timestamp__lt=last,
    ).order_by('timestamp').values_list(*keys)
    series = defaultdict(lambda: ([], []))
    for owner_id, entry_type, *rest in qs:
        if kind == 'monitor':
            processor, ts, *values = rest
        else:
            processor, (ts, *values) = None, rest
        value = values[stats.index(by_type[entry_type])]
        if value is None:
            continue
        times, vals = series[_series_key(kind, owner_id, entry_type, processor)]
        times.append(ts)
        vals.append(value)
    return series
