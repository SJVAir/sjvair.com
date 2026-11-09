import math
from datetime import datetime, timedelta

from camp.apps.entries.models import BaseEntry
from camp.apps.summaries.periods import iter_hours, period_end

WINDOW_HOURS = 8
MIN_WINDOW_HOURS = 6
PEAK_STATISTICS = ('max_1h', 'max_8h')


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


def peak_entry_models() -> dict[type, str]:
    result = {}
    for model in BaseEntry.get_subclasses():
        levels = getattr(model, 'Levels', None)
        statistic = getattr(levels, 'daily_statistic', None)
        if statistic in PEAK_STATISTICS:
            result[model] = statistic
    return result


def standard_for(entry_model) -> float:
    return float(entry_model.Levels.UNHEALTHY_SENSITIVE.value)
