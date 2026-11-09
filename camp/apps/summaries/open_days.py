"""
Open-day rows: daily summaries for days the nightly rollup hasn't written yet
(today so far, and yesterday until the rollup's settle time), built on request
from the stored hourly rows and never saved.
"""
from collections import defaultdict
from datetime import datetime, timedelta

from django.db.models import Q

from camp.apps.summaries.aggregators import rollup_region_stats, rollup_summaries
from camp.apps.summaries.models import BaseSummary, MonitorSummary, RegionSummary
from camp.apps.summaries.peaks import (
    DAILY_FIGURES, NEXT_DAY_HOURS, PEAK_FUNCTIONS, SENTINEL_MAX, SO_FAR_FUNCTIONS,
    day_hours, standard_for,
)
from camp.apps.summaries.periods import period_end, period_start
from camp.apps.summaries.schedule import is_settled

STATS_COLUMNS = (
    'count', 'expected_count', 'sum_value', 'sum_of_squares', 'minimum', 'maximum',
    'tdigest', 'mean',
)


def open_days(now: datetime) -> list[datetime]:
    """
    The Pacific day starts that may be open at `now`, today last: today, plus
    yesterday until the plain day settle margin has passed since it ended
    (whether a stored row exists is the caller's per-series check).
    """
    today = period_start('day', now)
    if is_settled('day', today, now=now):
        return [today]
    return [period_start('day', today - timedelta(hours=1)), today]


def _daily_statistic(entry_model):
    statistic = getattr(getattr(entry_model, 'Levels', None), 'daily_statistic', None)
    return statistic if statistic in DAILY_FIGURES else None


def build_open_rows(
    kind: str, owner_ids: list, entry_model, now: datetime, processor_q: Q | None = None,
) -> dict:
    """
    Unsaved DAILY rows (MonitorSummary or RegionSummary) for each series of
    `entry_model` among `owner_ids`, one per open day that has hourly rows.
    Yesterday is left out for a series that already has a stored daily row.
    Stats roll up every hourly row of the day; the figure (only the field the
    entry model's `daily_statistic` names) uses complete monitor hours / any
    region hour with a mean above SENTINEL_MAX: so far for today, strict for an
    earlier day (its max_8h windows may reach into the next day's first hours).
    `processor_q` filters monitor series; None means every processor.

    Returns {owner_id: [rows]} ordered by series then day; owners with no rows
    are absent. Runs one hourly query, plus one stored-daily query when
    yesterday is open.
    """
    if kind == 'monitor':
        model, owner = MonitorSummary, 'monitor_id'
        extra = ('processor', 'is_complete')
    elif kind == 'region':
        model, owner = RegionSummary, 'region_id'
        extra = ('weight', 'station_count')
    else:
        raise ValueError(f'Unknown kind: {kind}')

    days = open_days(now)
    today = days[-1]
    entry_type = entry_model.entry_type

    base = model.objects.filter(**{f'{owner}__in': owner_ids}, entry_type=entry_type)
    if kind == 'monitor' and processor_q is not None:
        base = base.filter(processor_q)

    def series_key(row):
        if kind == 'monitor':
            return (row[owner], row['processor'])
        return (row[owner],)

    hourly = base.filter(
        resolution=BaseSummary.Resolution.HOURLY,
        timestamp__gte=days[0],
        timestamp__lt=period_end('day', today) + timedelta(hours=NEXT_DAY_HOURS),
    ).order_by('timestamp').values(owner, 'timestamp', *STATS_COLUMNS, *extra)

    series = defaultdict(list)
    for row in hourly:
        series[series_key(row)].append(row)
    if not series:
        return {}

    stored = set()
    if len(days) > 1:
        stored_qs = base.filter(resolution=BaseSummary.Resolution.DAILY, timestamp=days[0])
        fields = (owner, 'processor') if kind == 'monitor' else (owner,)
        stored = set(stored_qs.values_list(*fields))

    statistic = _daily_statistic(entry_model)
    standard = standard_for(entry_model) if statistic else None

    result = defaultdict(list)
    for key in sorted(series, key=lambda k: tuple(str(v) for v in k)):
        rows = series[key]
        figure_input = {
            r['timestamp']: r['mean'] for r in rows
            if r['mean'] > SENTINEL_MAX and (kind == 'region' or r['is_complete'])
        }
        for day in days:
            if day != today and key in stored:
                continue
            day_end = period_end('day', day)
            day_rows = [r for r in rows if day <= r['timestamp'] < day_end]
            if kind == 'monitor':
                stats = rollup_summaries(day_rows)
            else:
                stats = rollup_region_stats(day_rows)
            if stats is None:
                continue

            figures = dict.fromkeys(DAILY_FIGURES)
            if statistic:
                hours = day_hours(day)
                if day == today:
                    figures[statistic] = SO_FAR_FUNCTIONS[statistic](hours, figure_input)
                else:
                    figures[statistic] = PEAK_FUNCTIONS[statistic](hours, figure_input, standard)

            fields = dict(
                entry_type=entry_type, resolution=BaseSummary.Resolution.DAILY,
                timestamp=day, **stats, **figures,
            )
            if kind == 'monitor':
                row = MonitorSummary(monitor_id=key[0], processor=key[1], **fields)
            else:
                station_count = max(r['station_count'] for r in day_rows)
                row = RegionSummary(region_id=key[0], station_count=station_count, **fields)
            result[key[0]].append(row)
    return dict(result)
