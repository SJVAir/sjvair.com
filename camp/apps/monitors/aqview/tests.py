import hashlib
import io
import os
import tempfile
import zipfile
from datetime import datetime, timezone as dt_timezone
from decimal import Decimal

from unittest.mock import patch

import pytest

from django.contrib.gis.geos import Point
from django.core.management import CommandError, call_command
from django.test import TestCase

from camp.apps.entries import models as entry_models
from camp.apps.monitors.aqview import history
from camp.apps.monitors.aqview.models import AQview
from camp.apps.monitors.models import LatestEntry


def wall_clock_ms(*args):
    '''A local clock time encoded the way AQview's `maptime` is: as if it were UTC.'''
    return int(datetime(*args, tzinfo=dt_timezone.utc).timestamp() * 1000)


def make_payload(maptime, hourindex=1, aobs=6.2):
    return {'maptime': maptime, 'hourindex': hourindex, 'aobs': aobs, 'sitename': 'Grimmway Elementary'}


def utc(*args):
    return datetime(*args, tzinfo=dt_timezone.utc)


class GetTimestampTests(TestCase):
    def test_maptime_is_the_local_hour_end_during_daylight_time(self):
        # 2026-10-21 12:00 local (PDT) ends the 11:00-12:00 PDT hour, 18:00 UTC.
        payload = make_payload(1792584000000, hourindex=24)

        assert AQview.get_timestamp(payload) == utc(2026, 10, 21, 18)

    def test_hourindex_is_not_subtracted(self):
        maptime = wall_clock_ms(2026, 10, 21, 12)

        assert AQview.get_timestamp(make_payload(maptime, hourindex=1)) == AQview.get_timestamp(make_payload(maptime, hourindex=24))

    def test_standard_time(self):
        # 12:00 PST ends the 11:00-12:00 PST hour, 19:00 UTC.
        assert AQview.get_timestamp(make_payload(wall_clock_ms(2026, 1, 15, 12))) == utc(2026, 1, 15, 19)

    def test_spring_forward(self):
        # Clocks jump 02:00 -> 03:00 PDT on 2026-03-08; the 01:00-02:00 PST hour ends at 03:00 PDT.
        assert AQview.get_timestamp(make_payload(wall_clock_ms(2026, 3, 8, 3))) == utc(2026, 3, 8, 9)

    def test_matches_aqview_download_tool(self):
        # Edison High School: the feed's maptime 2026-10-22 09:00 local held 7.2, which CARB's
        # download tool lists as MeasurementStartTime 2026-10-22 07:00 (PST), 15:00 UTC.
        assert AQview.get_timestamp(make_payload(wall_clock_ms(2026, 10, 22, 9), hourindex=2)) == utc(2026, 10, 22, 15)


class HandlePayloadTests(TestCase):
    def test_entry_is_stored_at_the_hour_start(self):
        monitor = AQview.objects.create(
            name='Grimmway Elementary',
            position=Point(-119.2871, 35.4912, srid=4326),
            location=AQview.LOCATION.outside,
        )

        entry = monitor.handle_payload(make_payload(1792584000000, hourindex=24))

        assert isinstance(entry, entry_models.PM25)
        assert entry.timestamp == utc(2026, 10, 21, 18)
        assert entry.stage == entry_models.PM25.Stage.RAW


HEADER = ('County,AB617Community,DataProvider,Site,Latitude,Longitude,Elevation,Instrument,MonitorId,ParameterId,'
          'Parameter,MeasurementStartTime,MeasuredValue,AdjustedValue,Units,AdjustmentDesc,LowerLimitCheck,'
          'UpperLimitCheck,RepeatValueCheck,SpikeCheck,DataProviderFlag,QC1Result,VerifiedByProvider,LastUpdateDate')


def csv_row(start, value, site='Edison High School', flag='', county='Fresno', parameter_id='88101', monitor_id='BAM 1022', adjusted=''):
    return (f'{county},South Central Fresno,San Joaquin Valley APCD,{site},36.7207,-119.8046,92,Met One {monitor_id},'
            f'{monitor_id},{parameter_id},PM2.5 - Local Conditions,{start},{value},{adjusted},ug/m3 (LC),,Pass,Pass,Pass,'
            f'Pass,{flag},{"Invalidated by Data Provider" if flag else "Pass"},,')


class ImportHistoryTests(TestCase):
    def setUp(self):
        self.monitor = AQview.objects.create(
            name='Edison High School',
            position=Point(-119.8046, 36.7207, srid=4326),
            location=AQview.LOCATION.outside,
        )

    def write_csv(self, *rows):
        handle = tempfile.NamedTemporaryFile('w', suffix='.csv', delete=False)
        handle.write('\n'.join([HEADER, *rows]) + '\n')
        handle.close()
        self.addCleanup(os.unlink, handle.name)
        return handle.name

    def import_rows(self, *rows):
        return history.import_aqview_history([self.write_csv(*rows)])

    def get_entries(self, stage):
        return list(entry_models.PM25.objects.filter(monitor=self.monitor, stage=stage).order_by('timestamp'))

    def test_measurement_start_time_is_pst_all_year(self):
        # 07:00 PST is 15:00 UTC in October (during PDT) as well as January.
        self.import_rows(csv_row('2026-10-22 07:00:00', '7.20'), csv_row('2026-01-15 07:00:00', '9.10'))

        assert [e.timestamp for e in self.get_entries('raw')] == [utc(2026, 1, 15, 15), utc(2026, 10, 22, 15)]

    def test_matches_the_live_feed_hour(self):
        # The download tool's 07:00 PST row is the live feed's maptime 09:00 PDT row.
        self.import_rows(csv_row('2026-10-22 07:00:00', '7.20'))

        assert self.get_entries('raw')[0].timestamp == AQview.get_timestamp(make_payload(wall_clock_ms(2026, 10, 22, 9), hourindex=2))

    def test_spring_forward_keeps_every_hour(self):
        self.import_rows(*[csv_row(f'2026-03-08 {h:02}:00:00', '5.00') for h in range(4)])

        assert [e.timestamp for e in self.get_entries('raw')] == [utc(2026, 3, 8, 8 + h) for h in range(4)]

    def test_raw_and_cleaned(self):
        self.import_rows(csv_row('2026-10-22 07:00:00', '-2.29'), csv_row('2026-10-22 08:00:00', '-15.00'))

        raw = self.get_entries('raw')
        cleaned = self.get_entries('cleaned')
        assert [e.value for e in raw] == [Decimal('-2.29'), Decimal('-15.00')]
        # The FEM cleaner clamps small negatives to 0 and drops values below -10.
        assert [e.value for e in cleaned] == [Decimal('0')]
        assert cleaned[0].origin_id == raw[0].pk

    def test_adjusted_value_preferred(self):
        self.import_rows(csv_row('2026-10-22 07:00:00', '7.20', adjusted='6.90'))

        assert self.get_entries('raw')[0].value == Decimal('6.90')

    def test_skips_invalidated_rows(self):
        totals = self.import_rows(csv_row('2026-10-22 07:00:00', '16.00', flag='Invalid'), csv_row('2026-10-22 08:00:00', '7.20'))

        assert [e.timestamp for e in self.get_entries('raw')] == [utc(2026, 10, 22, 16)]
        assert totals['invalid'] == 1

    def test_skips_other_parameters_devices_and_counties(self):
        self.import_rows(
            csv_row('2026-10-22 07:00:00', '7.20', parameter_id='44201'),
            csv_row('2026-10-22 08:00:00', '7.20', monitor_id='PA-II'),
            csv_row('2026-10-22 09:00:00', '7.20', county='Los Angeles'),
        )

        assert not entry_models.PM25.objects.exists()

    def test_replaces_stored_entries_in_the_range(self):
        PM25 = entry_models.PM25
        # Written by the old live import: off the hour, inside the file's range.
        stale = self.monitor.create_entry(PM25, timestamp=utc(2026, 10, 22, 15, 53), value=Decimal('12.50'))
        self.monitor.process_entry_ng(stale)
        outside = self.monitor.create_entry(PM25, timestamp=utc(2026, 10, 22, 20, 53), value=Decimal('3.00'))

        totals = self.import_rows(csv_row('2026-10-22 07:00:00', '7.20'), csv_row('2026-10-22 08:00:00', '8.10'))

        raw = self.get_entries('raw')
        assert [(e.timestamp, e.value) for e in raw] == [
            (utc(2026, 10, 22, 15), Decimal('7.20')),
            (utc(2026, 10, 22, 16), Decimal('8.10')),
            (utc(2026, 10, 22, 20, 53), Decimal('3.00')),
        ]
        assert raw[-1].pk == outside.pk
        assert totals['removed'] == 2
        assert not LatestEntry.objects.filter(entry_id=stale.pk).exists()

    def test_invalidated_hours_still_clear_stale_entries(self):
        stale = self.monitor.create_entry(entry_models.PM25, timestamp=utc(2026, 10, 22, 15), value=Decimal('12.50'))

        self.import_rows(csv_row('2026-10-22 07:00:00', '16.00', flag='Invalid'))

        assert not entry_models.PM25.objects.filter(pk=stale.pk).exists()

    def test_months_together_cover_the_whole_range(self):
        PM25 = entry_models.PM25
        # The file has Oct 30 and Dec 2; nothing in between, including all of November.
        gap = [self.monitor.create_entry(PM25, timestamp=ts, value=Decimal('1.00')) for ts in
               (utc(2026, 10, 31, 12, 53), utc(2026, 11, 15, 12, 53), utc(2026, 12, 1, 12, 53))]

        self.import_rows(csv_row('2026-10-30 07:00:00', '7.20'), csv_row('2026-12-02 07:00:00', '8.10'))

        assert not PM25.objects.filter(pk__in=[e.pk for e in gap]).exists()
        assert [e.timestamp for e in self.get_entries('raw')] == [utc(2026, 10, 30, 15), utc(2026, 12, 2, 15)]

    def test_split_by_month_bounds(self):
        hours = {utc(2026, 10, 30, 15): 'a', utc(2026, 10, 31, 3): 'b', utc(2026, 12, 2, 15): 'c'}

        pieces = history.split_by_month(hours)

        assert [(start, end, sorted(piece.values())) for start, end, piece in pieces] == [
            (utc(2026, 10, 30, 15), utc(2026, 12, 2, 15), ['a', 'b']),
            (utc(2026, 12, 2, 15), utc(2026, 12, 2, 16), ['c']),
        ]

    def test_updates_latest_entries(self):
        self.import_rows(csv_row('2026-10-22 07:00:00', '7.20'), csv_row('2026-10-22 08:00:00', '8.10'))

        latest = {l.stage: l for l in LatestEntry.objects.filter(monitor=self.monitor, entry_type='pm25')}
        assert set(latest) == {'cleaned'}
        assert latest['cleaned'].timestamp == utc(2026, 10, 22, 16)

    def test_rerun_is_idempotent(self):
        rows = [csv_row('2026-10-22 07:00:00', '7.20'), csv_row('2026-10-22 08:00:00', '8.10')]
        self.import_rows(*rows)
        self.import_rows(*rows)

        assert entry_models.PM25.objects.filter(monitor=self.monitor).count() == 4

    def test_creates_missing_monitors(self):
        self.import_rows(csv_row('2026-10-22 07:00:00', '7.20', site='New School'))

        monitor = AQview.objects.get(name='New School')
        assert monitor.device == 'BAM 1022'
        assert monitor.data_provider == 'San Joaquin Valley APCD'

    def test_reads_zip_files(self):
        path = self.write_csv(csv_row('2026-10-22 07:00:00', '7.20'))
        archive = path.replace('.csv', '.zip')
        with zipfile.ZipFile(archive, 'w') as handle:
            handle.write(path, 'Hourly-Records-2026-10-22-to-2026-10-22.csv')
        self.addCleanup(os.unlink, archive)

        history.import_aqview_history([archive])

        assert len(self.get_entries('raw')) == 1


class ImportHistoryStdinTests(TestCase):
    """Reading the download from stdin: `heroku run --no-tty -- ... import_aqview_history - < file.zip`."""

    setUp = ImportHistoryTests.setUp
    write_csv = ImportHistoryTests.write_csv
    get_entries = ImportHistoryTests.get_entries

    def make_zip(self, *rows):
        csv_path = self.write_csv(*rows)
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as handle:
            handle.write(csv_path, 'Hourly-Records.csv')
        return buffer.getvalue()

    def run_with_stdin(self, data, *args):
        stdout = io.StringIO()
        with patch('sys.stdin', io.TextIOWrapper(io.BytesIO(data))):
            call_command('import_aqview_history', '-', *args, stdout=stdout)
        return stdout.getvalue()

    def test_imports_a_zip_from_stdin(self):
        data = self.make_zip(csv_row('2026-10-22 07:00:00', '7.20'))

        output = self.run_with_stdin(data, '--sha256', hashlib.sha256(data).hexdigest())

        assert f'Read {len(data)} bytes from stdin, sha256 {hashlib.sha256(data).hexdigest()}' in output
        assert len(self.get_entries('raw')) == 1

    def test_imports_a_csv_from_stdin(self):
        data = open(self.write_csv(csv_row('2026-10-22 07:00:00', '7.20')), 'rb').read()

        self.run_with_stdin(data)

        assert len(self.get_entries('raw')) == 1

    def test_checksum_mismatch_imports_nothing(self):
        data = self.make_zip(csv_row('2026-10-22 07:00:00', '7.20'))

        with pytest.raises(CommandError, match='does not match'):
            self.run_with_stdin(data, '--sha256', '0' * 64)

        assert not entry_models.PM25.objects.exists()

    def test_empty_stdin(self):
        with pytest.raises(CommandError, match='Nothing was read'):
            self.run_with_stdin(b'')
