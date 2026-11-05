from datetime import datetime, timedelta

from django.conf import settings
from django.contrib.gis.geos import Point
from django.core.management import call_command
from django.test import TestCase

from camp.utils.datetime import make_aware
from camp.apps.entries.models import PM25, Temperature
from camp.apps.monitors.cimis.models import CIMIS
from camp.apps.monitors.models import Monitor
from camp.apps.monitors.purpleair.models import PurpleAir
from camp.apps.summaries.aggregators import compute_stats
from camp.apps.summaries.models import BaseSummary, MonitorSummary, RegionSummary, SummaryBackfillJob
from camp.apps.summaries.selection import (
    is_summarized,
    monitor_summary_entry_models,
    monitor_types_summarizing,
    region_summary_entry_models,
    switch_entry_types,
)
from camp.apps.summaries.tasks import backfill_summaries_tick, check_summary_integrity, hourly_monitor_summaries


R = BaseSummary.Resolution

CIMIS_TYPES = {
    'temperature', 'humidity', 'dewpoint', 'soiltemperature', 'windspeed', 'precipitation',
    'solarradiation', 'netradiation', 'vaporpressure', 'eto', 'etr',
}


def _day(y, m, d):
    return make_aware(datetime(y, m, d), settings.DEFAULT_TIMEZONE)


class SelectionTests(TestCase):
    def test_cimis_summarizes_eleven_types(self):
        # is_summarized honours the model flag for every monitor type, so the
        # air-quality types come along (CIMIS has no rows of them); the
        # weather types opted in through ENTRY_CONFIG are exactly these 11.
        types = {m.entry_type for m in monitor_summary_entry_models(CIMIS)}
        region_types = {m.entry_type for m in region_summary_entry_models()}
        assert types - region_types == CIMIS_TYPES
        assert 'winddirection' not in types

    def test_monitor_types_are_sorted_by_entry_type(self):
        types = [m.entry_type for m in monitor_summary_entry_models(CIMIS)]
        assert types == sorted(types)

    def test_accepts_a_monitor_instance(self):
        monitor = CIMIS(name='Station', station_number='1')
        assert monitor_summary_entry_models(monitor) == monitor_summary_entry_models(CIMIS)

    def test_purpleair_temperature_is_not_summarized(self):
        assert not is_summarized(PurpleAir, Temperature) and is_summarized(PurpleAir, PM25)

    def test_purpleair_keeps_the_region_types(self):
        assert monitor_summary_entry_models(PurpleAir) == region_summary_entry_models()

    def test_region_types_are_the_model_flag_types(self):
        assert {m.__name__ for m in region_summary_entry_models()} == {'PM25', 'O3', 'CO', 'NO2', 'SO2'}

    def test_switch_types_are_the_cimis_types(self):
        assert switch_entry_types() == frozenset(CIMIS_TYPES)

    def test_monitor_types_summarizing_temperature_is_only_cimis(self):
        assert monitor_types_summarizing(Temperature) == [CIMIS]

    def test_monitor_types_summarizing_pm25_is_every_monitor_type(self):
        assert monitor_types_summarizing(PM25) == Monitor.get_subclasses()


class SelectionCallSiteTests(TestCase):
    fixtures = ['purple-air.yaml']

    def setUp(self):
        self.cimis = CIMIS.objects.create(
            name='Station A',
            station_number='2',
            position=Point(-119.7871, 36.7378, srid=4326),
            location=CIMIS.LOCATION.outside,
        )
        self.purpleair = PurpleAir.objects.first()
        self.hour = _day(2026, 7, 1) + timedelta(hours=12)

    def _temperature(self, monitor, hour, value=20.0, minute=0):
        return Temperature.objects.create(
            monitor=monitor, timestamp=hour + timedelta(minutes=minute),
            stage=Temperature.Stage.RAW, processor='', value=value, location=monitor.location,
        )

    def _rebuild(self, monitor):
        call_command(
            'rebuild_summaries', '2026-07-01', '2026-07-02',
            monitor=str(monitor.pk), monitors_only=True, stdout=open('/dev/null', 'w'),
        )

    def test_rebuild_for_a_cimis_station_writes_weather_rows_and_no_region_rows(self):
        self._temperature(self.cimis, self.hour)
        self._rebuild(self.cimis)
        hourly = MonitorSummary.objects.filter(monitor=self.cimis, resolution=R.HOURLY)
        assert list(hourly.values_list('entry_type', 'timestamp')) == [('temperature', self.hour)]
        assert MonitorSummary.objects.filter(
            monitor=self.cimis, resolution=R.DAILY, entry_type='temperature',
        ).exists()
        assert not RegionSummary.objects.exists()

    def test_rebuild_for_a_purpleair_writes_no_temperature_rows(self):
        self._temperature(self.purpleair, self.hour)
        PM25.objects.create(
            monitor=self.purpleair, timestamp=self.hour, stage=PM25.Stage.RAW,
            processor='', value=10.0, location=self.purpleair.location,
        )
        self._rebuild(self.purpleair)
        types = set(MonitorSummary.objects.filter(monitor=self.purpleair).values_list('entry_type', flat=True))
        assert types == {'pm25'}

    def test_rebuild_async_for_a_cimis_station_writes_weather_rows(self):
        self._temperature(self.cimis, self.hour)
        self._temperature(self.purpleair, self.hour)
        call_command(
            'rebuild_summaries', '2026-07-01', '2026-07-02', '--async',
            monitors_only=True, stdout=open('/dev/null', 'w'),
        )
        rows = set(MonitorSummary.objects.filter(resolution=R.HOURLY).values_list('monitor_id', 'entry_type'))
        assert rows == {(self.cimis.pk, 'temperature')}

    def test_hourly_monitor_parent_skips_weather(self):
        self._temperature(self.cimis, self.hour)
        hourly_monitor_summaries(self.hour)
        assert not MonitorSummary.objects.exists()

    def test_backfill_job_summarizes_cimis_weather_types(self):
        for i in range(3):
            self._temperature(self.cimis, self.hour + timedelta(hours=i), value=20.0 + i)
        call_command(
            'backfill_summaries', 'start', '--from', '2026-07-01', '--to', '2026-07-02',
            stdout=open('/dev/null', 'w'),
        )
        for _ in range(50):
            SummaryBackfillJob.objects.update(locked_at=None)
            with self.captureOnCommitCallbacks(execute=True):
                backfill_summaries_tick()
            if SummaryBackfillJob.objects.get().state != SummaryBackfillJob.State.RUNNING:
                break
        assert SummaryBackfillJob.objects.get().state == SummaryBackfillJob.State.DONE

        hourly = MonitorSummary.objects.filter(monitor=self.cimis, resolution=R.HOURLY, entry_type='temperature')
        assert hourly.count() == 3
        daily = MonitorSummary.objects.get(monitor=self.cimis, resolution=R.DAILY, entry_type='temperature')
        assert daily.count == 3
        assert not RegionSummary.objects.filter(entry_type='temperature').exists()

    def test_integrity_check_ignores_weather_only_hours(self):
        MonitorSummary.objects.create(
            monitor=self.cimis, timestamp=self.hour, resolution=R.HOURLY,
            entry_type='temperature', processor='', **compute_stats([20.0], 1),
        )
        result = check_summary_integrity.call_local(now=_day(2026, 7, 2) + timedelta(hours=3))
        assert result['missing_region_hours'] == 0

    def test_integrity_check_still_reports_air_quality_hours(self):
        MonitorSummary.objects.create(
            monitor=self.purpleair, timestamp=self.hour, resolution=R.HOURLY,
            entry_type='pm25', processor='', **compute_stats([10.0], 1),
        )
        result = check_summary_integrity.call_local(now=_day(2026, 7, 2) + timedelta(hours=3))
        assert result['missing_region_hours'] == 1
