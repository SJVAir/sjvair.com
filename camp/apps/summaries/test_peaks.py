from datetime import datetime, timedelta

from django.conf import settings
from django.test import TestCase

from camp.apps.entries import models as entries
from camp.apps.summaries.peaks import (
    day_hours, max_1h, max_8h, peak_entry_models, standard_for,
)
from camp.utils.datetime import make_aware


def day(y, m, d):
    return day_hours(make_aware(datetime(y, m, d), settings.DEFAULT_TIMEZONE))


def series(hours, values, start=0):
    return {hours[start + i]: v for i, v in enumerate(values)}


class PeakMathTests(TestCase):
    def test_max_1h_full_day(self):
        hours = day(2026, 7, 1)
        hourly = series(hours, [10.0] * 23 + [130.0])
        assert max_1h(hours, hourly, 125) == 130.0

    def test_max_1h_threshold(self):
        hours = day(2026, 7, 1)
        assert max_1h(hours, series(hours, [50.0] * 18), 125) == 50.0
        assert max_1h(hours, series(hours, [50.0] * 17), 125) is None

    def test_max_1h_short_day_over_standard(self):
        hours = day(2026, 7, 1)
        assert max_1h(hours, series(hours, [1, 2, 125, 3, 4]), 125) == 125.0
        assert max_1h(hours, series(hours, [1, 2, 124.9, 3, 4]), 125) is None

    def test_max_1h_dst_days(self):
        spring = day(2026, 3, 8)
        assert len(spring) == 23
        assert max_1h(spring, series(spring, [5.0] * 18), 125) == 5.0
        assert max_1h(spring, series(spring, [5.0] * 17), 125) is None
        fall = day(2026, 11, 1)
        assert len(fall) == 25
        assert max_1h(fall, series(fall, [5.0] * 19), 125) == 5.0
        assert max_1h(fall, series(fall, [5.0] * 18), 125) is None

    def test_zero_and_negative_count_as_data(self):
        hours = day(2026, 7, 1)
        hourly = series(hours, [-0.5] * 9 + [0.0] * 9)
        assert max_1h(hours, hourly, 125) == 0.0

    def test_max_8h_window_validity(self):
        hours = day(2026, 7, 1)
        # Only 6 hours at 10 starting at 00:00: window 0 averages those 6.
        hourly = series(hours, [10.0] * 6)
        assert max_8h(hours, hourly, 9.5) == 10.0
        # 5 hours: no valid window.
        assert max_8h(hours, series(hours, [10.0] * 5), 9.5) is None

    def test_max_8h_threshold(self):
        hours = day(2026, 7, 1)
        # Data in hours 0..22: a window needs >= 6 hours, so windows 0..17 (18) are valid.
        assert max_8h(hours, series(hours, [1.0] * 23), 9.5) == 1.0
        # Data in hours 0..21: windows 0..16 (17) are valid, under the 75% rule.
        assert max_8h(hours, series(hours, [1.0] * 22), 9.5) is None
        # Still 17 windows, but the peak meets the standard.
        hourly = series(hours, [1.0] * 14 + [20.0] * 8)
        assert max_8h(hours, hourly, 9.5) == 20.0

    def test_max_8h_uses_next_day(self):
        hours = day(2026, 7, 1)
        nxt = day(2026, 7, 2)
        hourly = series(hours, [1.0] * 24)
        base = max_8h(hours, hourly, 9.5)
        for h in nxt[:7]:
            hourly[h] = 20.0
        raised = max_8h(hours, hourly, 9.5)
        assert base == 1.0
        assert raised > base

    def test_max_8h_missing_next_day(self):
        hours = day(2026, 7, 1)
        hourly = series(hours, [2.0] * 24)
        assert max_8h(hours, hourly, 9.5) == 2.0

    def test_peak_entry_models(self):
        assert peak_entry_models() == {
            entries.O3: 'max_1h',
            entries.NO2: 'max_1h',
            entries.SO2: 'max_1h',
            entries.CO: 'max_8h',
        }
        assert entries.PM25 not in peak_entry_models()

    def test_standard_for(self):
        assert standard_for(entries.CO) == 9.5
        assert standard_for(entries.O3) == 125.0
