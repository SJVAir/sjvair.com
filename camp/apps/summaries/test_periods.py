from datetime import datetime, timezone as dt_timezone

from django.conf import settings
from django.test import TestCase

from camp.apps.summaries.periods import (
    is_period_start,
    iter_hours,
    iter_period_starts,
    period_end,
    period_start,
)

PT = settings.DEFAULT_TIMEZONE


def pacific(*args):
    return datetime(*args, tzinfo=PT)


def utc(*args):
    return datetime(*args, tzinfo=dt_timezone.utc)


def both(ts):
    """The same instant as Pacific and as UTC."""
    return [ts, ts.astimezone(dt_timezone.utc)]


class PeriodsTests(TestCase):
    def test_day_across_fall_back(self):
        for ts in both(pacific(2026, 11, 1, 12)):
            start = period_start('day', ts)
            assert start == utc(2026, 11, 1, 7)  # 2026-11-01T00:00-07:00
            end = period_end('day', ts)
            assert end == utc(2026, 11, 2, 8)  # 2026-11-02T00:00-08:00
            assert (end.astimezone(dt_timezone.utc) - start.astimezone(dt_timezone.utc)).total_seconds() == 25 * 3600

    def test_month_late_evening_belongs_to_february(self):
        for ts in both(utc(2026, 3, 1, 7)):
            assert period_start('month', ts) == utc(2026, 2, 1, 8)  # 2026-02-01T00:00-08:00

    def test_season_quarter_year(self):
        for ts in both(pacific(2026, 1, 15)):
            assert period_start('season', ts) == utc(2025, 12, 1, 8)
        for ts in both(pacific(2026, 3, 1)):
            assert period_start('season', ts) == utc(2026, 3, 1, 8)
        for ts in both(pacific(2026, 11, 5)):
            assert period_start('quarter', ts) == utc(2026, 10, 1, 7)
        for ts in both(pacific(2026, 7, 4)):
            assert period_start('year', ts) == utc(2026, 1, 1, 8)

    def test_hour_truncates_in_utc(self):
        for ts in both(pacific(2026, 11, 1, 1, 45)):  # first 01:45 PDT
            assert period_start('hour', ts) == utc(2026, 11, 1, 8)

    def test_iter_hours_across_fall_back(self):
        for start, end in [
            (pacific(2026, 11, 1, 0), pacific(2026, 11, 1, 4)),
            tuple(t.astimezone(dt_timezone.utc) for t in (pacific(2026, 11, 1, 0), pacific(2026, 11, 1, 4))),
        ]:
            assert list(iter_hours(start, end)) == [utc(2026, 11, 1, h) for h in (7, 8, 9, 10, 11)]

    def test_iter_hours_across_spring_forward(self):
        hours = list(iter_hours(pacific(2026, 3, 8, 0), pacific(2026, 3, 8, 4)))
        assert hours == [utc(2026, 3, 8, 8), utc(2026, 3, 8, 9), utc(2026, 3, 8, 10)]

    def test_iter_period_starts_day(self):
        got = list(iter_period_starts('day', pacific(2026, 10, 31), pacific(2026, 11, 3)))
        assert got == [utc(2026, 10, 31, 7), utc(2026, 11, 1, 7), utc(2026, 11, 2, 8)]

    def test_iter_period_starts_season_starts_before_range(self):
        got = list(iter_period_starts('season', pacific(2026, 1, 10), pacific(2026, 6, 2)))
        assert got == [utc(2025, 12, 1, 8), utc(2026, 3, 1, 8), utc(2026, 6, 1, 7)]

    def test_is_period_start(self):
        assert not is_period_start('month', pacific(2026, 2, 28, 23))
        assert is_period_start('month', pacific(2026, 2, 1))
        assert is_period_start('day', utc(2026, 11, 2, 8))
