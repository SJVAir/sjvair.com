import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta

from django.db import transaction

from camp.apps.entries.models import BaseEntry
from camp.apps.summaries.models import BaseSummary, MonitorSummary, RegionSummary
from camp.apps.summaries.periods import iter_hours, period_end

WINDOW_HOURS = 8
MIN_WINDOW_HOURS = 6
DAILY_FIGURES = ('max_1h', 'max_8h', 'mean_24h')

# An hourly mean at or below this is a "missing" marker (AirNow stored -999 before
# its importer was fixed), not a reading.
SENTINEL_MAX = -900.0


@dataclass
class FillResult:
    updated: dict[str, int]  # rows updated (or that would be), per entry type
    skipped: int  # hourly rows read and dropped as sentinels


def day_hours(day_start: datetime) -> list[datetime]:
    return list(iter_hours(day_start, period_end('day', day_start)))


def _threshold(n: int) -> int:
    return math.ceil(0.75 * n)


def _gate(peak, count, n, standard):
    """Return the peak if coverage is enough or it meets the standard."""
    if peak is None:
        return None
    if count >= _threshold(n) or peak >= standard:
        return float(peak)
    return None


def max_1h(day_hours, hourly, standard):
    values = [hourly[h] for h in day_hours if h in hourly]
    if not values:
        return None
    return _gate(max(values), len(values), len(day_hours), standard)


def max_8h(day_hours, hourly, standard):
    averages = []
    for h in day_hours:
        values = [
            hourly[t]
            for t in (h + timedelta(hours=k) for k in range(WINDOW_HOURS))
            if t in hourly
        ]
        if len(values) >= MIN_WINDOW_HOURS:
            averages.append(sum(values) / len(values))
    if not averages:
        return None
    return _gate(max(averages), len(averages), len(day_hours), standard)


def mean_24h(day_hours, hourly, standard=None):
    """Mean of the hourly means; needs 75% of the day's hours. No standard exception."""
    values = [hourly[h] for h in day_hours if h in hourly]
    if len(values) < _threshold(len(day_hours)):
        return None
    return float(sum(values) / len(values))


def peak_entry_models() -> dict[type, str]:
    result = {}
    for model in BaseEntry.get_subclasses():
        levels = getattr(model, 'Levels', None)
        statistic = getattr(levels, 'daily_statistic', None)
        if statistic in DAILY_FIGURES:
            result[model] = statistic
    return result


def standard_for(entry_model) -> float:
    return float(entry_model.Levels.UNHEALTHY_SENSITIVE.value)


# How far past a day's end its last 8-hour window reaches.
NEXT_DAY_HOURS = WINDOW_HOURS - 1

PEAK_FUNCTIONS = {'max_1h': max_1h, 'max_8h': max_8h, 'mean_24h': mean_24h}

# Owners read together: one daily-rows query and one hourly query per group.
OWNER_GROUP_SIZE = 200
# Caps a group's hourly read for long spans (a month: ~66 owners per group).
OWNER_HOURS_PER_GROUP = 50_000


def fill_daily_peaks(
    kind: str, ids: list | None, start: datetime, end: datetime, *,
    entry_models: list | None = None, fields: tuple[str, ...] = DAILY_FIGURES,
    dry_run: bool = False, batch_size: int = 1000, progress=None,
) -> FillResult:
    """
    Write `max_1h` / `max_8h` / `mean_24h` on DAILY rows with `start <= timestamp < end` of the
    peak entry types (or the given subset of them). `kind` is 'monitor' or
    'region'; `ids=None` means all. Each row gets its own statistic; the other
    fields are set to null. Only `fields` are written, and only rows whose values
    change. Hourly means at or below `SENTINEL_MAX` count as no data. Returns a
    `FillResult`: the rows updated (or that would be) per entry type, and how many
    hourly rows were skipped as sentinels among those read (a next-day tail hour
    read for a max_8h window counts too, and an hour read for several rows once).
    """
    if kind == 'monitor':
        model, owner = MonitorSummary, 'monitor_id'
    elif kind == 'region':
        model, owner = RegionSummary, 'region_id'
    else:
        raise ValueError(f'Unknown kind: {kind}')

    fields = tuple(fields)
    peaks = peak_entry_models()
    if entry_models is not None:
        peaks = {m: stat for m, stat in peaks.items() if m in entry_models}
    by_type = {m.entry_type: (m, stat) for m, stat in peaks.items()}
    if not by_type or not fields:
        return FillResult({}, 0)

    daily = model.objects.filter(
        resolution=BaseSummary.Resolution.DAILY,
        timestamp__gte=start,
        timestamp__lt=end,
        entry_type__in=list(by_type),
    )
    if ids is not None:
        daily = daily.filter(**{f'{owner}__in': ids})

    owner_ids = list(daily.order_by(owner).values_list(owner, flat=True).distinct())
    group_size = _owner_group_size(start, end)
    columns = ['id', owner.removesuffix('_id'), 'entry_type', 'timestamp', *fields]
    if kind == 'monitor':
        columns.append('processor')

    counts = Counter()
    skipped = 0
    pending = []

    def flush():
        if not pending:
            return
        if not dry_run:
            with transaction.atomic():
                model.objects.bulk_update(pending, fields, batch_size=batch_size)
        if progress is not None:
            progress(f'{kind} peaks: {len(pending)} rows {"would be " if dry_run else ""}updated')
        pending.clear()

    for i in range(0, len(owner_ids), group_size):
        group = owner_ids[i:i + group_size]
        rows = list(daily.filter(**{f'{owner}__in': group}).only(*columns))
        hourly, group_skipped = _hourly_series(model, owner, group, rows, kind)
        skipped += group_skipped

        for row in rows:
            entry_model, statistic = by_type[row.entry_type]
            key = _series_key(kind, getattr(row, owner), row.entry_type, getattr(row, 'processor', None))
            series = hourly.get(key, {})
            value = PEAK_FUNCTIONS[statistic](day_hours(row.timestamp), series, standard_for(entry_model))

            changed = False
            for field in fields:
                new = value if field == statistic else None
                if getattr(row, field) != new:
                    setattr(row, field, new)
                    changed = True
            if changed:
                counts[row.entry_type] += 1
                pending.append(row)
                if len(pending) >= batch_size:
                    flush()

    flush()
    return FillResult(dict(counts), skipped)


def _owner_group_size(start, end):
    """Owners per read: OWNER_GROUP_SIZE for a day, fewer for longer spans, so a
    group's hourly read stays near OWNER_HOURS_PER_GROUP owner-hours."""
    span_hours = (end - start) / timedelta(hours=1) + NEXT_DAY_HOURS
    return max(1, min(OWNER_GROUP_SIZE, int(OWNER_HOURS_PER_GROUP // max(span_hours, 1))))


def _series_key(kind, owner_id, entry_type, processor):
    if kind == 'monitor':
        return (owner_id, entry_type, processor)
    return (owner_id, entry_type)


def _hourly_series(model, owner, owner_ids, rows, kind):
    """One read of a group of owners' hourly means covering their daily rows' days
    (plus the next day's first hours for 8-hour windows), keyed by series then hour,
    and the number of sentinel hours dropped."""
    if not rows:
        return {}, 0
    first = min(r.timestamp for r in rows)
    last = max(r.timestamp for r in rows)
    qs = model.objects.filter(
        **{f'{owner}__in': owner_ids},
        resolution=BaseSummary.Resolution.HOURLY,
        entry_type__in={r.entry_type for r in rows},
        timestamp__gte=first,
        timestamp__lt=period_end('day', last) + timedelta(hours=NEXT_DAY_HOURS),
    )
    series = defaultdict(dict)
    skipped = 0
    if kind == 'monitor':
        qs = qs.filter(is_complete=True)
        rows = qs.values_list(owner, 'entry_type', 'processor', 'timestamp', 'mean')
    else:
        rows = qs.values_list(owner, 'entry_type', 'timestamp', 'mean')
    for *key, ts, mean in rows:
        if mean <= SENTINEL_MAX:
            skipped += 1
            continue
        series[tuple(key)][ts] = mean
    return series, skipped
