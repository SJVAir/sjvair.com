from datetime import datetime, timedelta
from decimal import Decimal

from django.conf import settings
from django.test import TestCase
from django.utils import timezone

from camp.apps.entries import models as entry_models
from camp.apps.monitors.legacy_backfill import (
    LEGACY_BACKFILL_MAP, build_raw_entry, chunk_start_for, find_missing_raw_entries,
    monitors_with_legacy_data_in,
)
from camp.apps.monitors.models import Entry
from camp.apps.monitors.airnow.models import AirNow
from camp.apps.monitors.aqview.models import AQview
from camp.apps.monitors.bam.models import BAM1022
from camp.apps.monitors.purpleair.models import PurpleAir
from camp.utils.datetime import make_aware


def _legacy_entry(monitor, **kwargs):
    defaults = {
        'monitor': monitor,
        'sensor': '',
        'location': Entry._meta.get_field('location').choices[0][0],
    }
    defaults.update(kwargs)
    return Entry(**defaults)


class BuildRawEntryPurpleAirTests(TestCase):
    def setUp(self):
        self.monitor = PurpleAir(name='Test PurpleAir', sensor_id=1, location='outside')

    def test_pm25_uses_reported_only_not_calibrated(self):
        legacy = _legacy_entry(
            self.monitor, sensor='a', pm25=Decimal('12.00'), pm25_reported=Decimal('9.50'),
        )
        mapping = LEGACY_BACKFILL_MAP[PurpleAir][entry_models.PM25]
        entry = build_raw_entry(self.monitor, legacy, entry_models.PM25, mapping)
        assert entry.value == Decimal('9.50')
        assert entry.sensor == 'a'

    def test_pm25_returns_none_when_reported_missing(self):
        legacy = _legacy_entry(self.monitor, sensor='a', pm25=Decimal('12.00'), pm25_reported=None)
        mapping = LEGACY_BACKFILL_MAP[PurpleAir][entry_models.PM25]
        assert build_raw_entry(self.monitor, legacy, entry_models.PM25, mapping) is None

    def test_particulates_copies_all_fields_directly(self):
        legacy = _legacy_entry(
            self.monitor, sensor='b',
            particles_03um=Decimal('1.1'), particles_05um=Decimal('2.2'),
            particles_10um=Decimal('3.3'), particles_25um=Decimal('4.4'),
            particles_50um=Decimal('5.5'), particles_100um=Decimal('6.6'),
        )
        mapping = LEGACY_BACKFILL_MAP[PurpleAir][entry_models.Particulates]
        entry = build_raw_entry(self.monitor, legacy, entry_models.Particulates, mapping)
        assert entry.particles_03um == Decimal('1.1')
        assert entry.particles_100um == Decimal('6.6')
        assert entry.sensor == 'b'

    def test_particulates_returns_none_when_any_field_missing(self):
        legacy = _legacy_entry(
            self.monitor, sensor='b',
            particles_03um=Decimal('1.1'), particles_05um=None,
            particles_10um=Decimal('3.3'), particles_25um=Decimal('4.4'),
            particles_50um=Decimal('5.5'), particles_100um=Decimal('6.6'),
        )
        mapping = LEGACY_BACKFILL_MAP[PurpleAir][entry_models.Particulates]
        assert build_raw_entry(self.monitor, legacy, entry_models.Particulates, mapping) is None

    def test_temperature_and_humidity_and_pressure_collapse_sensor_to_blank(self):
        legacy = _legacy_entry(
            self.monitor, sensor='a', fahrenheit=Decimal('70.5'),
            humidity=Decimal('40.0'), pressure=Decimal('1013.25'),
        )
        temp = build_raw_entry(
            self.monitor, legacy, entry_models.Temperature,
            LEGACY_BACKFILL_MAP[PurpleAir][entry_models.Temperature],
        )
        humidity = build_raw_entry(
            self.monitor, legacy, entry_models.Humidity,
            LEGACY_BACKFILL_MAP[PurpleAir][entry_models.Humidity],
        )
        assert temp.sensor == ''
        assert temp.fahrenheit == Decimal('70.5')
        assert humidity.sensor == ''
        assert humidity.value == Decimal('40.0')

    def test_pressure_hpa_converted_to_mmhg(self):
        legacy = _legacy_entry(self.monitor, sensor='a', pressure=Decimal('1013.25'))
        mapping = LEGACY_BACKFILL_MAP[PurpleAir][entry_models.Pressure]
        entry = build_raw_entry(self.monitor, legacy, entry_models.Pressure, mapping)
        # 1013.25 hPa -> mmHg via the model's own hpa setter (1 hPa = 1/1.33322 mmHg)
        expected = (Decimal('1013.25') / Decimal('1.33322')).quantize(Decimal('0.01'))
        assert entry.value == expected

    def test_raw_entry_uses_legacy_position_and_location(self):
        legacy = _legacy_entry(self.monitor, sensor='a', pm25_reported=Decimal('5.0'), location='inside')
        mapping = LEGACY_BACKFILL_MAP[PurpleAir][entry_models.PM25]
        entry = build_raw_entry(self.monitor, legacy, entry_models.PM25, mapping)
        assert entry.location == 'inside'
        assert entry.stage == entry_models.PM25.Stage.RAW
        assert entry.processor == ''


class BuildRawEntryCoalesceTests(TestCase):
    def test_airnow_prefers_reported_falls_back_to_pm25(self):
        monitor = AirNow(name='Test AirNow', location='outside')
        legacy = _legacy_entry(monitor, pm25=Decimal('8.0'), pm25_reported=None)
        mapping = LEGACY_BACKFILL_MAP[AirNow][entry_models.PM25]
        entry = build_raw_entry(monitor, legacy, entry_models.PM25, mapping)
        assert entry.value == Decimal('8.0')

    def test_airnow_prefers_reported_when_both_present(self):
        monitor = AirNow(name='Test AirNow', location='outside')
        legacy = _legacy_entry(monitor, pm25=Decimal('8.0'), pm25_reported=Decimal('7.5'))
        mapping = LEGACY_BACKFILL_MAP[AirNow][entry_models.PM25]
        entry = build_raw_entry(monitor, legacy, entry_models.PM25, mapping)
        assert entry.value == Decimal('7.5')

    def test_aqview_coalesce_same_as_airnow(self):
        monitor = AQview(name='Test AQview', location='outside')
        legacy = _legacy_entry(monitor, pm25=Decimal('3.0'), pm25_reported=None)
        mapping = LEGACY_BACKFILL_MAP[AQview][entry_models.PM25]
        entry = build_raw_entry(monitor, legacy, entry_models.PM25, mapping)
        assert entry.value == Decimal('3.0')


class BuildRawEntryBamTests(TestCase):
    def setUp(self):
        self.monitor = BAM1022(name='Test BAM', location='outside')

    def test_pm25_coalesces_and_skips_sentinel(self):
        mapping = LEGACY_BACKFILL_MAP[BAM1022][entry_models.PM25]
        legacy = _legacy_entry(self.monitor, pm25=Decimal('99999'), pm25_reported=None)
        assert build_raw_entry(self.monitor, legacy, entry_models.PM25, mapping) is None

    def test_pm25_sentinel_check_uses_pm25_not_reported(self):
        mapping = LEGACY_BACKFILL_MAP[BAM1022][entry_models.PM25]
        legacy = _legacy_entry(self.monitor, pm25=Decimal('4.2'), pm25_reported=Decimal('4.2'))
        entry = build_raw_entry(self.monitor, legacy, entry_models.PM25, mapping)
        assert entry.value == Decimal('4.2')

    def test_pressure_mmhg_copied_directly_no_conversion(self):
        mapping = LEGACY_BACKFILL_MAP[BAM1022][entry_models.Pressure]
        legacy = _legacy_entry(self.monitor, pressure=Decimal('750.00'))
        entry = build_raw_entry(self.monitor, legacy, entry_models.Pressure, mapping)
        assert entry.value == Decimal('750.00')

    def test_celsius_converted_to_fahrenheit(self):
        mapping = LEGACY_BACKFILL_MAP[BAM1022][entry_models.Temperature]
        legacy = _legacy_entry(self.monitor, celsius=Decimal('20.0'))
        entry = build_raw_entry(self.monitor, legacy, entry_models.Temperature, mapping)
        # 20C -> 68F via the model's own celsius setter
        assert entry.value == Decimal('68.0')


def _ts(*args):
    return make_aware(datetime(*args), settings.DEFAULT_TIMEZONE)


class ChunkStartForTests(TestCase):
    def test_steps_back_by_chunk_days(self):
        cursor = _ts(2023, 7, 15)
        range_start = _ts(2020, 1, 1)
        assert chunk_start_for(cursor, range_start, chunk_days=7) == cursor - timedelta(days=7)

    def test_clamps_to_range_start(self):
        cursor = _ts(2020, 1, 4)
        range_start = _ts(2020, 1, 1)
        assert chunk_start_for(cursor, range_start, chunk_days=7) == range_start


class FindMissingRawEntriesTests(TestCase):
    fixtures = ['purple-air.yaml']

    def setUp(self):
        self.monitor = PurpleAir.objects.first()
        self.window_start = _ts(2023, 1, 1)
        self.window_end = _ts(2023, 1, 8)

    def test_finds_legacy_row_with_no_new_entry(self):
        Entry.objects.create(
            monitor=self.monitor, sensor='a', timestamp=self.window_start + timedelta(hours=1),
            location=self.monitor.location, pm25_reported=Decimal('5.0'),
        )
        mapping = LEGACY_BACKFILL_MAP[PurpleAir][entry_models.PM25]
        missing = find_missing_raw_entries(
            self.monitor, entry_models.PM25, mapping, self.window_start, self.window_end,
        )
        assert len(missing) == 1
        assert missing[0].value == Decimal('5.0')

    def test_skips_legacy_row_that_already_has_a_new_entry(self):
        ts = self.window_start + timedelta(hours=1)
        Entry.objects.create(
            monitor=self.monitor, sensor='a', timestamp=ts,
            location=self.monitor.location, pm25_reported=Decimal('5.0'),
        )
        entry_models.PM25.objects.create(
            monitor=self.monitor, sensor='a', timestamp=ts, location=self.monitor.location,
            stage=entry_models.PM25.Stage.RAW, processor='', value=Decimal('5.0'),
        )
        mapping = LEGACY_BACKFILL_MAP[PurpleAir][entry_models.PM25]
        missing = find_missing_raw_entries(
            self.monitor, entry_models.PM25, mapping, self.window_start, self.window_end,
        )
        assert missing == []

    def test_detects_interior_gap_not_just_head_or_tail(self):
        # Three legacy rows; only the middle one is missing its new-entry counterpart.
        timestamps = [self.window_start + timedelta(hours=h) for h in (1, 2, 3)]
        for i, ts in enumerate(timestamps):
            Entry.objects.create(
                monitor=self.monitor, sensor='a', timestamp=ts,
                location=self.monitor.location, pm25_reported=Decimal(f'{i}.0'),
            )
        for i, ts in enumerate(timestamps):
            if i == 1:
                continue  # leave the middle one un-migrated
            entry_models.PM25.objects.create(
                monitor=self.monitor, sensor='a', timestamp=ts, location=self.monitor.location,
                stage=entry_models.PM25.Stage.RAW, processor='', value=Decimal(f'{i}.0'),
            )
        mapping = LEGACY_BACKFILL_MAP[PurpleAir][entry_models.PM25]
        missing = find_missing_raw_entries(
            self.monitor, entry_models.PM25, mapping, self.window_start, self.window_end,
        )
        assert len(missing) == 1
        assert missing[0].timestamp == timestamps[1]

    def test_per_sensor_false_dedups_across_a_and_b_rows(self):
        ts = self.window_start + timedelta(hours=1)
        for sensor in ('a', 'b'):
            Entry.objects.create(
                monitor=self.monitor, sensor=sensor, timestamp=ts,
                location=self.monitor.location, humidity=Decimal('40.0'),
            )
        mapping = LEGACY_BACKFILL_MAP[PurpleAir][entry_models.Humidity]
        missing = find_missing_raw_entries(
            self.monitor, entry_models.Humidity, mapping, self.window_start, self.window_end,
        )
        assert len(missing) == 1
        assert missing[0].sensor == ''


class MonitorsWithLegacyDataInTests(TestCase):
    fixtures = ['purple-air.yaml']

    def test_finds_monitor_with_legacy_data_in_window(self):
        monitor = PurpleAir.objects.first()
        window_start = _ts(2023, 1, 1)
        window_end = _ts(2023, 1, 8)
        Entry.objects.create(
            monitor=monitor, sensor='a', timestamp=window_start + timedelta(hours=1),
            location=monitor.location, pm25_reported=Decimal('5.0'),
        )
        ids = monitors_with_legacy_data_in(window_start, window_end)
        assert monitor.pk in ids

    def test_excludes_monitor_with_no_data_in_window(self):
        monitor = PurpleAir.objects.first()
        window_start = _ts(2023, 1, 1)
        window_end = _ts(2023, 1, 8)
        ids = monitors_with_legacy_data_in(window_start, window_end)
        assert monitor.pk not in ids
