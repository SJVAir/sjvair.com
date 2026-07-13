from datetime import datetime, timedelta

from django.conf import settings
from django.test import TestCase

from camp.utils.datetime import make_aware
from camp.apps.summaries.models import BaseSummary
from camp.apps.summaries.backfill import (
    chunk_start_for,
    hour_range,
    iter_chunk_days,
    daily_rollup_window,
    higher_rollup_windows,
)


def _day(y, m, d):
    return make_aware(datetime(y, m, d), settings.DEFAULT_TIMEZONE)


class ChunkStartForTests(TestCase):
    def test_steps_back_seven_days(self):
        cursor = _day(2023, 7, 15)
        range_start = _day(2020, 1, 1)
        assert chunk_start_for(cursor, range_start) == cursor - timedelta(days=7)

    def test_clamps_to_range_start(self):
        cursor = _day(2020, 1, 4)
        range_start = _day(2020, 1, 1)
        assert chunk_start_for(cursor, range_start) == range_start


class HourRangeTests(TestCase):
    def test_yields_each_hour_exclusive_of_end(self):
        start = _day(2023, 1, 1)
        end = start + timedelta(hours=3)
        hours = list(hour_range(start, end))
        assert hours == [start, start + timedelta(hours=1), start + timedelta(hours=2)]


class IterChunkDaysTests(TestCase):
    def test_yields_each_day_exclusive_of_end(self):
        start = _day(2023, 1, 1)
        end = start + timedelta(days=3)
        days = list(iter_chunk_days(start, end))
        assert days == [start, start + timedelta(days=1), start + timedelta(days=2)]


class DailyRollupWindowTests(TestCase):
    def test_returns_daily_window(self):
        day = _day(2023, 7, 15)
        target, source, window_start, window_end = daily_rollup_window(day)
        assert target == BaseSummary.Resolution.DAILY
        assert source == BaseSummary.Resolution.HOURLY
        assert window_start == day
        assert window_end == day + timedelta(days=1)


class HigherRollupWindowsTests(TestCase):
    def test_mid_month_day_has_no_higher_windows(self):
        assert higher_rollup_windows(_day(2023, 7, 15)) == []

    def test_ordinary_month_start_rolls_up_month_only(self):
        windows = higher_rollup_windows(_day(2023, 8, 1))
        resolutions = [w[0] for w in windows]
        assert resolutions == [BaseSummary.Resolution.MONTHLY]

    def test_quarter_start_month_cascades_to_quarterly(self):
        windows = higher_rollup_windows(_day(2023, 7, 1))
        resolutions = [w[0] for w in windows]
        assert BaseSummary.Resolution.MONTHLY in resolutions
        assert BaseSummary.Resolution.QUARTERLY in resolutions
        assert BaseSummary.Resolution.SEASONAL not in resolutions
        assert BaseSummary.Resolution.YEARLY not in resolutions

    def test_season_start_month_cascades_to_seasonal(self):
        windows = higher_rollup_windows(_day(2023, 6, 1))
        resolutions = [w[0] for w in windows]
        assert BaseSummary.Resolution.SEASONAL in resolutions

    def test_december_is_season_start_but_not_quarter_start(self):
        windows = higher_rollup_windows(_day(2023, 12, 1))
        resolutions = [w[0] for w in windows]
        assert BaseSummary.Resolution.SEASONAL in resolutions
        assert BaseSummary.Resolution.QUARTERLY not in resolutions

    def test_january_cascades_to_quarterly_and_yearly(self):
        windows = higher_rollup_windows(_day(2023, 1, 1))
        resolutions = [w[0] for w in windows]
        assert BaseSummary.Resolution.MONTHLY in resolutions
        assert BaseSummary.Resolution.QUARTERLY in resolutions
        assert BaseSummary.Resolution.YEARLY in resolutions

    def test_quarterly_window_spans_three_months(self):
        windows = higher_rollup_windows(_day(2023, 7, 1))
        quarterly = next(w for w in windows if w[0] == BaseSummary.Resolution.QUARTERLY)
        _, _, window_start, window_end = quarterly
        assert window_start == _day(2023, 7, 1)
        assert window_end == _day(2023, 10, 1)

    def test_yearly_window_spans_twelve_months(self):
        windows = higher_rollup_windows(_day(2023, 1, 1))
        yearly = next(w for w in windows if w[0] == BaseSummary.Resolution.YEARLY)
        _, _, window_start, window_end = yearly
        assert window_start == _day(2023, 1, 1)
        assert window_end == _day(2024, 1, 1)
