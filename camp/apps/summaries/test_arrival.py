from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from django.conf import settings
from django.contrib.gis.geos import Point
from django.test import TestCase

from camp.apps.entries.models import Precipitation, Temperature
from camp.apps.monitors.cimis.models import CIMIS
from camp.apps.monitors.purpleair.models import PurpleAir
from camp.apps.summaries.models import BaseSummary, MonitorSummary, RegionSummary
from camp.apps.summaries.periods import iter_hours
from camp.apps.summaries.tasks import rollup_windows_for, summarize_monitor_hours
from camp.utils.datetime import make_aware


R = BaseSummary.Resolution
LA = settings.DEFAULT_TIMEZONE


def pacific(*args):
    return make_aware(datetime(*args), LA)


def frozen(now):
    return patch('django.utils.timezone.now', return_value=now)


class RollupWindowsForTests(TestCase):
    def test_unfinished_month_is_not_rolled(self):
        hour = pacific(2026, 1, 14, 12)
        windows = rollup_windows_for([hour], pacific(2026, 1, 15, 10))
        assert windows[R.DAILY] == [pacific(2026, 1, 14)]
        assert not windows.get(R.MONTHLY)
        assert not windows.get(R.QUARTERLY)
        assert not windows.get(R.SEASONAL)
        assert not windows.get(R.YEARLY)

    def test_unfinished_day_is_not_rolled(self):
        hour = pacific(2026, 1, 14, 12)
        windows = rollup_windows_for([hour], pacific(2026, 1, 14, 13))
        assert not windows.get(R.DAILY)

    def test_finished_month_is_rolled_and_windows_are_distinct(self):
        hours = [pacific(2026, 1, 31, 22), pacific(2026, 1, 31, 23)]
        windows = rollup_windows_for(hours, pacific(2026, 2, 1, 10))
        assert windows[R.DAILY] == [pacific(2026, 1, 31)]
        assert windows[R.MONTHLY] == [pacific(2026, 1, 1)]
        # Q1 and the Dec-Feb season are still running; the year too.
        assert not windows.get(R.QUARTERLY)
        assert not windows.get(R.SEASONAL)
        assert not windows.get(R.YEARLY)

    def test_no_widening_to_neighbouring_days(self):
        hours = [pacific(2026, 1, 14, 23), pacific(2026, 1, 15, 0)]
        windows = rollup_windows_for(hours, pacific(2026, 1, 20))
        assert windows[R.DAILY] == [pacific(2026, 1, 14), pacific(2026, 1, 15)]


class SummarizeMonitorHoursTests(TestCase):
    fixtures = ['purple-air.yaml']

    def setUp(self):
        self.monitor = CIMIS.objects.create(
            name='Station A',
            station_number='2',
            position=Point(-119.7871, 36.7378, srid=4326),
            location=CIMIS.LOCATION.outside,
        )

    def _entry(self, EntryModel, monitor, hour, value):
        return EntryModel.objects.create(
            monitor=monitor, timestamp=hour,
            stage=EntryModel.Stage.RAW, processor='', value=value, location=monitor.location,
        )

    def _row(self, entry_type, resolution, timestamp):
        return MonitorSummary.objects.get(
            monitor=self.monitor, entry_type=entry_type, resolution=resolution, timestamp=timestamp,
        )

    def test_daily_sum_is_the_total_of_the_hours(self):
        hours = [pacific(2026, 1, 14, h) for h in (9, 10, 11)]
        for hour in hours:
            self._entry(Precipitation, self.monitor, hour, 0.01)

        with frozen(pacific(2026, 1, 15, 10)):
            summarize_monitor_hours(str(self.monitor.pk), hours)

        assert MonitorSummary.objects.filter(
            monitor=self.monitor, entry_type=Precipitation.entry_type, resolution=R.HOURLY,
        ).count() == 3
        daily = self._row(Precipitation.entry_type, R.DAILY, pacific(2026, 1, 14))
        assert daily.count == 3
        assert daily.sum_value == pytest.approx(0.03)

    def test_today_is_summarized_hourly_but_not_rolled(self):
        hour = pacific(2026, 1, 14, 9)
        self._entry(Temperature, self.monitor, hour, 50)

        with frozen(pacific(2026, 1, 14, 10, 45)):
            summarize_monitor_hours(str(self.monitor.pk), [hour])

        assert self._row(Temperature.entry_type, R.HOURLY, hour)
        assert not MonitorSummary.objects.filter(monitor=self.monitor, resolution=R.DAILY).exists()

    def test_late_reading_in_a_finished_month_rerolls_the_month(self):
        day = pacific(2026, 1, 31)
        hours = list(iter_hours(day, pacific(2026, 2, 1)))
        missing = hours[5]
        for hour in hours:
            if hour != missing:
                self._entry(Temperature, self.monitor, hour, 50)

        with frozen(pacific(2026, 2, 1, 10)):
            summarize_monitor_hours(str(self.monitor.pk), hours)
        assert self._row(Temperature.entry_type, R.MONTHLY, pacific(2026, 1, 1)).count == 23

        self._entry(Temperature, self.monitor, missing, 50)
        with frozen(pacific(2026, 2, 2, 10)):
            summarize_monitor_hours(str(self.monitor.pk), [missing])

        assert self._row(Temperature.entry_type, R.DAILY, day).count == 24
        assert self._row(Temperature.entry_type, R.MONTHLY, pacific(2026, 1, 1)).count == 24
        assert not MonitorSummary.objects.filter(
            monitor=self.monitor, resolution__in=[R.QUARTERLY, R.SEASONAL, R.YEARLY],
        ).exists()

    def test_never_writes_region_rows(self):
        hour = pacific(2026, 1, 14, 9)
        self._entry(Temperature, self.monitor, hour, 50)

        with frozen(pacific(2026, 1, 15, 10)):
            summarize_monitor_hours(str(self.monitor.pk), [hour])

        assert MonitorSummary.objects.filter(monitor=self.monitor).exists()
        assert not RegionSummary.objects.exists()

    def test_air_sensor_temperature_is_not_summarized_by_summarize_monitor_hours(self):
        purpleair = PurpleAir.objects.first()
        hour = pacific(2026, 1, 14, 9)
        self._entry(Temperature, purpleair, hour, 70)

        with frozen(pacific(2026, 1, 15, 10)):
            summarize_monitor_hours(str(purpleair.pk), [hour])

        assert not MonitorSummary.objects.filter(monitor=purpleair).exists()
        assert not RegionSummary.objects.exists()
