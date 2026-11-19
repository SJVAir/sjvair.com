"""
The rows of the month, quarter, season and year holding yesterday, through
yesterday, written each night (`current_monitor_periods`,
`current_region_periods`) and by rebuilds whose range reaches yesterday.
"""
import logging
import math
from datetime import datetime, timedelta

from django.db import transaction
from django.db.models import Exists, OuterRef, Q, QuerySet
from django.utils import timezone

from camp.apps.summaries.models import BaseSummary, MonitorSummary, RegionSummary
from camp.apps.summaries.peaks import peak_entry_models
from camp.apps.summaries.period_stats import expected_days, fill_period_statistics
from camp.apps.summaries.periods import period_end, period_start

logger = logging.getLogger('camp.apps.summaries')

R = BaseSummary.Resolution

# (resolution, target, source), in order: the month first, so the coarser
# periods roll the partial month just written.
CURRENT_PERIODS = (
    ('month', R.MONTHLY, R.DAILY),
    ('quarter', R.QUARTERLY, R.MONTHLY),
    ('season', R.SEASONAL, R.MONTHLY),
    ('year', R.YEARLY, R.MONTHLY),
)


def reaches_yesterday(end: datetime, now: datetime) -> bool:
    """Whether a rebuild range ending at `end` includes yesterday (Pacific) as of `now`."""
    today = period_start('day', now)
    return end > period_start('day', today - timedelta(microseconds=1))


def _kind(kind):
    # tasks imports this module, so the rollups are imported here.
    from camp.apps.summaries.tasks import rollup_monitor_summaries, rollup_region_summaries
    if kind == 'monitor':
        return MonitorSummary, 'monitor_id', rollup_monitor_summaries
    if kind == 'region':
        return RegionSummary, 'region_id', rollup_region_summaries
    raise ValueError(f'Unknown kind: {kind}')


def roll_current_periods(
    kind: str, ids: list | None = None, now: datetime | None = None, *, clock=timezone.now,
) -> dict:
    """
    Write, for each resolution, the row of the one period holding yesterday,
    through yesterday. Periods come from `now` (default: `clock()`), never a
    scheduled date. A period still running at `now` is written with
    `is_partial=True`; on its first night a period that just ended is written
    in full (`is_partial=False`), the same row the regular rollup writes.

    With `ids`, exactly those owners are rolled. Without, a partial period
    rolls the owners with a DAILY row for yesterday, plus the owners with
    source rows in the period so far and no row for it yet (after a deploy
    or a backfill); the others' inputs haven't changed, so their partial rows
    get their expected days moved by one UPDATE per resolution. An ended
    period rolls every owner.

    Start of today is checked again before every write (and by the rollups
    before their upsert and fills): once midnight has passed since `now`, the
    run stops, so it never writes a partial row over a final one.

    Returns `{'rolled': {resolution: owners}, 'refreshed': {resolution: rows},
    'stopped': bool}`.
    """
    model, owner, rollup = _kind(kind)
    now = now if now is not None else clock()
    today = period_start('day', now)
    yesterday = period_start('day', today - timedelta(microseconds=1))

    def guard():
        return period_start('day', clock()) == today

    result = {'rolled': {}, 'refreshed': {}, 'stopped': False}

    def stop(resolution):
        logger.warning(
            'Current %s periods stopped at %s: the day changed since the run started (%s)',
            kind, resolution, today.date(),
        )
        result['stopped'] = True
        return result

    for resolution, target, source in CURRENT_PERIODS:
        start = period_start(resolution, yesterday)
        full_end = period_end(resolution, start)
        end = min(full_end, today)
        partial = full_end > today

        if ids is not None:
            owners = ids
        elif partial:
            owners = _nightly_owners(model, owner, target, source, start, today, yesterday)
        else:
            owners = None

        if owners is None or _any(owners):
            # Counted before the write: the nightly owners without a row leave
            # the sub-select once the rollup gives them one.
            owners_rolled = None if owners is None else _count(owners)
            if not guard():
                return stop(resolution)
            if not rollup(target, source, start, end, owners, is_partial=partial, guard=guard, now=now):
                return stop(resolution)
            if ids is None and partial:
                # The rollup's fill re-reads `owners` after its upsert, so it
                # skips the rows it just wrote for owners that had none.
                if not guard():
                    return stop(resolution)
                fill_period_statistics(
                    kind, _unfilled(model, owner, target, start), start, full_end,
                    resolutions=[target], now=now)
            if owners_rolled is None:
                owners_rolled = (
                    model.objects.filter(resolution=target, timestamp=start)
                    .order_by().values_list(owner, flat=True).distinct().count()
                )
            result['rolled'][resolution] = owners_rolled

        if ids is None and partial:
            # `owners` no longer holds the owners just given a first row, but
            # their rows already have today's expected days, so the UPDATE skips them.
            refreshed = _refresh(model, owner, target, start, today, owners, guard)
            if refreshed is None:
                return stop(resolution)
            result['refreshed'][resolution] = refreshed

    return result


def _nightly_owners(model, owner, target, source, start, today, yesterday):
    """
    The owners a nightly run rolls for a partial period: those with a DAILY
    row for yesterday, and those with source rows in [start, today) but no
    target row at `start` (owner-level: the rollup re-rolls all of an owner's
    series). Left unevaluated: every `__in` it reaches is a sub-select, never
    a list of every region's id inlined into the query.
    """
    has_row = model.objects.filter(
        resolution=target, timestamp=start, **{owner: OuterRef(owner)})
    return (
        model.objects.filter(
            Q(resolution=R.DAILY, timestamp=yesterday)
            | (Q(resolution=source, timestamp__gte=start, timestamp__lt=today) & ~Exists(has_row))
        )
        .order_by().values_list(owner, flat=True).distinct()
    )


def _unfilled(model, owner, target, start):
    """Owners with a partial row at `start` of a peak type the fill hasn't reached."""
    return (
        model.objects.filter(
            resolution=target, timestamp=start, is_partial=True,
            entry_type__in=[m.entry_type for m in peak_entry_models()],
            daily_statistic_days__isnull=True,
        )
        .order_by().values_list(owner, flat=True).distinct()
    )


def _any(owners):
    return owners.exists() if isinstance(owners, QuerySet) else bool(owners)


def _count(owners):
    return owners.count() if isinstance(owners, QuerySet) else len(owners)


def _refresh(model, owner, target, start, today, rolled, guard):
    """
    Move the expected days of the partial rows not just re-rolled: their
    inputs are unchanged, so only the day count and the 75% rule move.
    Returns the rows whose expected days changed, or None when the guard
    stopped it.
    """
    days = expected_days(start, today)
    rows = (
        model.objects.filter(
            resolution=target,
            timestamp=start,
            is_partial=True,
            entry_type__in=[m.entry_type for m in peak_entry_models()],
        )
        .exclude(**{f'{owner}__in': rolled})
    )
    with transaction.atomic():
        if not guard():
            return None
        updated = rows.exclude(daily_statistic_expected_days=days).update(
            daily_statistic_expected_days=days)
        if not guard():
            transaction.set_rollback(True)
            return None
        rows.filter(
            daily_statistic_days__lt=math.ceil(0.75 * days),
            daily_statistic_mean__isnull=False,
        ).update(daily_statistic_mean=None)
    return updated
