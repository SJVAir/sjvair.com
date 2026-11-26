from datetime import datetime, timedelta
from io import StringIO
from unittest.mock import patch

from django.conf import settings
from django.contrib.gis.geos import Point
from django.core.management import call_command
from django.test import TestCase

from camp.utils.datetime import make_aware
from camp.apps.entries.models import PM25, Temperature
from camp.apps.monitors.cimis.models import CIMIS
from camp.apps.monitors.models import Monitor
from camp.apps.monitors.purpleair.models import PurpleAir
from camp.apps.regions.models import Region
from camp.apps.summaries import repair
from camp.apps.summaries.aggregators import compute_stats
from camp.apps.summaries.models import BaseSummary, MonitorSummary, RegionSummary, SummaryBackfillJob
from camp.apps.summaries.selection import (
    is_summarized,
    monitor_summary_entry_models,
    monitor_types_summarizing,
    region_summary_entry_models,
    switch_entry_models,
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

    def test_switch_models_are_sorted_cimis_models(self):
        models = switch_entry_models()
        assert [m.entry_type for m in models] == sorted(CIMIS_TYPES)

    def test_monitor_types_summarizing_temperature_is_only_cimis(self):
        assert monitor_types_summarizing(Temperature) == [CIMIS]

    def test_monitor_types_summarizing_pm25_is_every_monitor_type(self):
        assert monitor_types_summarizing(PM25) == Monitor.get_subclasses()


class SelectionCallSiteTests(TestCase):
    fixtures = ['purple-air.yaml', 'regions.yaml']

    def setUp(self):
        self.region = Region.objects.filter(boundary__isnull=False).order_by('pk').first()
        inside = self.region.boundary.geometry.point_on_surface
        self.cimis = CIMIS.objects.create(
            name='Station A',
            station_number='2',
            position=Point(inside.x, inside.y, srid=4326),
            location=CIMIS.LOCATION.outside,
        )
        self.purpleair = PurpleAir.objects.first()
        self.purpleair.position = inside
        self.purpleair.save()
        self.hour = _day(2026, 7, 1) + timedelta(hours=12)

    def _temperature(self, monitor, hour, value=20.0):
        return Temperature.objects.create(
            monitor=monitor, timestamp=hour,
            stage=Temperature.Stage.RAW, processor='', value=value, location=monitor.location,
        )

    def _pm25(self, monitor, hour, value=10.0):
        return PM25.objects.create(
            monitor=monitor, timestamp=hour,
            stage=PM25.Stage.RAW, processor='', value=value, location=monitor.location,
        )

    def _hourly_row(self, monitor, entry_type, hour, value=10.0):
        return MonitorSummary.objects.create(
            monitor=monitor, timestamp=hour, resolution=R.HOURLY,
            entry_type=entry_type, processor='', **compute_stats([value], 1),
        )

    def _region_types(self):
        return set(RegionSummary.objects.values_list('entry_type', flat=True))

    def _rebuild(self, monitor, *args):
        call_command(
            'rebuild_summaries', '2026-07-01', '2026-07-02', *args,
            monitor=str(monitor.pk), stdout=StringIO(),
        )

    def test_cimis_station_is_inside_the_region(self):
        assert self.region.monitors.filter(pk=self.cimis.pk).exists()

    def test_rebuild_for_a_cimis_station_writes_weather_rows_and_no_region_rows(self):
        self._temperature(self.cimis, self.hour)
        self._rebuild(self.cimis, '--monitors-only')
        hourly = MonitorSummary.objects.filter(monitor=self.cimis, resolution=R.HOURLY)
        assert list(hourly.values_list('entry_type', 'timestamp')) == [('temperature', self.hour)]
        assert MonitorSummary.objects.filter(
            monitor=self.cimis, resolution=R.DAILY, entry_type='temperature',
        ).exists()
        assert not RegionSummary.objects.exists()

    def test_rebuild_with_regions_for_a_cimis_station_writes_no_weather_region_rows(self):
        self._temperature(self.cimis, self.hour)
        self._hourly_row(self.purpleair, 'pm25', self.hour)
        self._rebuild(self.cimis)
        assert MonitorSummary.objects.filter(monitor=self.cimis, entry_type='temperature').exists()
        assert self._region_types() == {'pm25'}

    def test_rebuild_for_a_purpleair_writes_no_temperature_rows(self):
        self._temperature(self.purpleair, self.hour)
        self._pm25(self.purpleair, self.hour)
        self._rebuild(self.purpleair, '--monitors-only')
        types = set(MonitorSummary.objects.filter(monitor=self.purpleair).values_list('entry_type', flat=True))
        assert types == {'pm25'}

    def test_rebuild_async_for_a_cimis_station_writes_weather_rows(self):
        self._temperature(self.cimis, self.hour)
        self._temperature(self.purpleair, self.hour)
        call_command(
            'rebuild_summaries', '2026-07-01', '2026-07-02', '--async',
            monitors_only=True, stdout=StringIO(),
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
            self._pm25(self.purpleair, self.hour + timedelta(hours=i))
        call_command(
            'backfill_summaries', 'start', '--from', '2026-07-01', '--to', '2026-07-02',
            stdout=StringIO(),
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
        # The region phase ran (the PurpleAir's pm25 has region rows) and wrote no weather rows.
        assert RegionSummary.objects.filter(region=self.region, resolution=R.HOURLY, entry_type='pm25').count() == 3
        assert self._region_types() == {'pm25'}

    def test_backfill_dispatch_checks_switch_types_only_on_their_monitor_types(self):
        from camp.apps.summaries.backfill import monitors_with_data_in
        self._temperature(self.cimis, self.hour)
        self._temperature(self.purpleair, self.hour)
        ids = monitors_with_data_in(
            _day(2026, 7, 1), _day(2026, 7, 2), region_summary_entry_models(),
            scoped_entry_models={m: monitor_types_summarizing(m) for m in switch_entry_models()},
        )
        assert ids == [self.cimis.pk]

    def test_repair_region_hours_writes_no_weather_region_rows(self):
        self._hourly_row(self.cimis, 'temperature', self.hour, 20.0)
        self._hourly_row(self.purpleair, 'pm25', self.hour)
        with patch('django.utils.timezone.now', return_value=_day(2026, 11, 4)):
            call_command(
                'repair_summaries', '2026-07-01', '2026-07-02',
                '--region', str(self.region.pk), '--region-hours', stdout=StringIO(),
            )
        assert RegionSummary.objects.filter(region=self.region, resolution=R.HOURLY, entry_type='pm25').exists()
        assert self._region_types() == {'pm25'}

    def test_missing_region_hours_ignores_weather_only_hours(self):
        self._hourly_row(self.cimis, 'temperature', self.hour, 20.0)
        missing = repair.missing_region_hours([self.region.pk], _day(2026, 7, 1), _day(2026, 7, 2))
        assert missing == {}

    def test_missing_region_hours_still_reports_air_quality_hours(self):
        self._hourly_row(self.purpleair, 'pm25', self.hour)
        missing = repair.missing_region_hours([self.region.pk], _day(2026, 7, 1), _day(2026, 7, 2))
        assert missing == {self.region.pk: [self.hour]}

    def test_integrity_check_ignores_weather_only_hours(self):
        self._hourly_row(self.cimis, 'temperature', self.hour, 20.0)
        result = check_summary_integrity.call_local(now=_day(2026, 7, 2) + timedelta(hours=3))
        assert result['missing_region_hours'] == 0

    def test_integrity_check_still_reports_air_quality_hours(self):
        self._hourly_row(self.purpleair, 'pm25', self.hour)
        result = check_summary_integrity.call_local(now=_day(2026, 7, 2) + timedelta(hours=3))
        assert result['missing_region_hours'] == 1
