import re
from decimal import Decimal
from datetime import date, datetime, timedelta, timezone as dt_timezone
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest

from django.contrib.gis.geos import Point
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from camp.apps.entries import models as entry_models
from camp.apps.monitors.cimis.models import CIMIS
from camp.apps.monitors.cimis.restamp import RestampResult, ShortAnswer, delete_window, restamp_station
from camp.apps.monitors.models import LatestEntry, Monitor
from camp.utils.datetime import localtime


HOURS = [f'{h:02d}00' for h in range(1, 25)]


def utc(day, hour):
    return datetime(day.year, day.month, day.day, tzinfo=dt_timezone.utc) + timedelta(hours=hour)


def make_record(day, hour, station='2', temp=None, humidity=None):
    '''A CIMIS hourly record. Values derive from the label unless given.'''
    hour_number = int(hour[:2])
    if temp is None:
        temp = 50 + hour_number + day.day / 10
    if humidity is None:
        humidity = 20 + hour_number
    return {
        'Date': day.isoformat(),
        'Hour': hour,
        'Station': station,
        'HlyAirTmp': {'Value': f'{temp:.1f}', 'Qc': ' ', 'Unit': '(F)'},
        'HlyRelHum': {'Value': str(humidity), 'Qc': ' ', 'Unit': '(%)'},
    }


def fake_api(station='2', days=None, error_on=None, temp_offset=0, extra=None, hours=None):
    '''
    An API stand-in returning 24 hours for every requested date (or only
    `days`, when given), and raising on the date `error_on`. `hours` maps a
    date to the labels answered for it (a partial day).
    '''
    def get_hourly_data(station_numbers, start_date, end_date, data_items):
        assert start_date == end_date
        if error_on is not None and start_date == error_on:
            raise RuntimeError('CIMIS is down')
        if days is not None and start_date not in days:
            return [{'Name': 'cimis', 'Records': []}]
        records = []
        for number in station_numbers:
            for hour in (hours or {}).get(start_date, HOURS):
                record = make_record(start_date, hour, station=number)
                record['HlyAirTmp']['Value'] = f"{float(record['HlyAirTmp']['Value']) + temp_offset:.1f}"
                records.append(record)
        records.extend(r for r in (extra or []) if r['Date'] == start_date.isoformat())
        return [{'Name': 'cimis', 'Records': records}]

    api = MagicMock()
    api.get_hourly_data.side_effect = get_hourly_data
    return api


def make_station(station_number='2'):
    return CIMIS.objects.create(
        name=f'CIMIS #{station_number}',
        station_number=station_number,
        position=Point(-119.7871, 36.7378, srid=4326),
        location=CIMIS.LOCATION.outside,
    )


def make_dash_station(station_number='2'):
    '''
        A station whose id starts with "-", as about 1 in 64 random ids do.
        A command line given it as a separate argument (`--monitor <id>`)
        reads it as an option; only `--monitor=<id>` works.
    '''
    import uuid
    from smalluuid import SmallUUID
    raw = bytearray(uuid.uuid4().bytes)
    raw[0] = 0xF8 | (raw[0] & 0x03)
    station = make_station(station_number)
    CIMIS.objects.filter(pk=station.pk).delete()
    station.pk = station.id = SmallUUID(bytes=bytes(raw))
    station.save(force_insert=True)
    assert str(station.pk).startswith('-')
    return station


def store_legacy(monitor, days, hours=HOURS):
    '''Store rows the way the old ingest did: end-of-hour Pacific wall clock.'''
    count = 0
    for day in days:
        for hour in hours:
            record = make_record(day, hour, station=monitor.station_number)
            timestamp = monitor.legacy_timestamp(record)
            monitor.create_entry(entry_models.Temperature, timestamp=timestamp, value=record['HlyAirTmp']['Value'])
            monitor.create_entry(entry_models.Humidity, timestamp=timestamp, value=record['HlyRelHum']['Value'])
            count += 2
    return count


def rows(monitor, EntryModel=entry_models.Temperature):
    return set(
        EntryModel.objects
        .filter(monitor_id=monitor.pk)
        .values_list('timestamp', 'value')
    )


def all_rows(monitor):
    return {
        EntryModel: rows(monitor, EntryModel)
        for EntryModel in CIMIS.ENTRY_CONFIG
    }


def through(end):
    '''Make `end` today (Pacific) for the restamp.'''
    return patch('camp.apps.monitors.cimis.restamp.today', return_value=end)


def restamp_through(monitor, end, **kwargs):
    with through(end):
        return restamp_station(monitor, **kwargs)


class RestampStationTests(TestCase):
    def setUp(self):
        self.monitor = make_station('2')

    def test_dry_run_counts_and_writes_nothing(self):
        days = [date(2025, 7, 15), date(2025, 7, 16)]
        stored = store_legacy(self.monitor, days)
        before = all_rows(self.monitor)
        latest_before = set(LatestEntry.objects.filter(monitor=self.monitor).values_list('entry_type', 'entry_id', 'timestamp'))

        result = restamp_through(self.monitor, end=days[-1], dry_run=True, api=fake_api())

        assert isinstance(result, RestampResult)
        assert result.monitor_id == self.monitor.pk
        assert result.start == days[0]
        assert result.end == days[-1]
        assert result.labels == 48
        assert result.deleted == stored
        assert result.deleted_by_type['temperature'] == stored // 2
        assert result.written == 0
        assert all_rows(self.monitor) == before
        latest_after = set(LatestEntry.objects.filter(monitor=self.monitor).values_list('entry_type', 'entry_id', 'timestamp'))
        assert latest_after == latest_before

    def test_nothing_stored_does_nothing(self):
        api = fake_api()

        result = restamp_through(self.monitor, end=date(2025, 7, 16), dry_run=False, api=api)

        assert result.start is None
        assert (result.labels, result.deleted, result.written) == (0, 0, 0)
        api.get_hourly_data.assert_not_called()

    def test_restamps_a_pdt_day_and_a_pst_day(self):
        # Spans the end of daylight saving (2025-11-02).
        days = [date(2025, 11, 1), date(2025, 11, 2), date(2025, 11, 3)]
        store_legacy(self.monitor, [days[0], days[2]])
        legacy_stamps = {
            self.monitor.legacy_timestamp(make_record(day, hour))
            for day in [days[0], days[2]] for hour in HOURS
        }

        result = restamp_through(self.monitor, end=days[-1], dry_run=False, api=fake_api())

        expected = {
            (self.monitor.parse_timestamp(make_record(day, hour)),
             Decimal(make_record(day, hour)['HlyAirTmp']['Value']))
            for day in days for hour in HOURS
        }
        assert rows(self.monitor) == expected
        assert result.labels == 72
        assert result.written == 72 * 2

        stamps = {timestamp for timestamp, _value in rows(self.monitor)}
        new_stamps = {self.monitor.parse_timestamp(make_record(day, hour)) for day in days for hour in HOURS}
        assert stamps == new_stamps
        assert not (stamps & (legacy_stamps - new_stamps))

        # A PDT day: 0100 is 00:00-01:00 PST, i.e. 08:00 UTC.
        assert utc(days[0], 8) in stamps
        # A PST day: 2400 is 23:00 PST, i.e. 07:00 UTC the next day.
        assert utc(days[2], 31) in stamps
        assert rows(self.monitor, entry_models.Humidity) == {
            (self.monitor.parse_timestamp(make_record(day, hour)), int(make_record(day, hour)['HlyRelHum']['Value']))
            for day in days for hour in HOURS
        }

    def test_running_twice_is_a_no_op(self):
        days = [date(2025, 1, 14), date(2025, 1, 15), date(2025, 1, 16)]
        store_legacy(self.monitor, days)

        restamp_through(self.monitor, end=days[-1], dry_run=False, api=fake_api())
        first = all_rows(self.monitor)
        latest_first = set(LatestEntry.objects.filter(monitor=self.monitor).values_list('entry_type', 'timestamp'))

        result = restamp_through(self.monitor, end=days[-1], dry_run=False, api=fake_api())

        assert result.start == days[0]
        assert all_rows(self.monitor) == first
        assert len(first[entry_models.Temperature]) == 72
        latest_second = set(LatestEntry.objects.filter(monitor=self.monitor).values_list('entry_type', 'timestamp'))
        assert latest_second == latest_first

    def test_first_hour_of_a_pst_range_is_kept(self):
        start = date(2025, 1, 14)
        store_legacy(self.monitor, [start, start + timedelta(days=1)])

        restamp_through(self.monitor, end=start + timedelta(days=1), dry_run=False, api=fake_api())
        restamp_through(self.monitor, end=start + timedelta(days=1), dry_run=False, api=fake_api())

        first_hour = entry_models.Temperature.objects.filter(monitor_id=self.monitor.pk, timestamp=utc(start, 8))
        assert first_hour.count() == 1
        assert str(first_hour.get().value) == make_record(start, '0100')['HlyAirTmp']['Value']
        assert self.monitor.parse_timestamp(make_record(start, '0100')) == utc(start, 8)
        assert entry_models.Temperature.objects.filter(monitor_id=self.monitor.pk).count() == 48

    def test_latest_entry_points_at_an_existing_entry_with_the_new_newest_timestamp(self):
        days = [date(2025, 7, 15), date(2025, 7, 16)]
        store_legacy(self.monitor, days)
        # Old stamps run an hour later than the new ones, so the old latest
        # timestamp is newer than anything the restamp writes.
        old_latest = LatestEntry.objects.get(monitor=self.monitor, entry_type='temperature')
        assert old_latest.timestamp == self.monitor.legacy_timestamp(make_record(days[-1], '2400'))

        restamp_through(self.monitor, end=days[-1], dry_run=False, api=fake_api())

        newest = self.monitor.parse_timestamp(make_record(days[-1], '2400'))
        for entry_type, EntryModel in [('temperature', entry_models.Temperature), ('humidity', entry_models.Humidity)]:
            latest = LatestEntry.objects.get(monitor=self.monitor, entry_type=entry_type)
            assert latest.timestamp == newest
            entry = EntryModel.objects.get(pk=latest.entry_id)
            assert entry.monitor_id == self.monitor.pk
            assert entry.timestamp == newest
        assert LatestEntry.objects.filter(monitor=self.monitor).count() == 2

    def test_api_error_leaves_the_station_untouched(self):
        days = [date(2025, 7, 15), date(2025, 7, 16)]
        store_legacy(self.monitor, days)
        before = all_rows(self.monitor)
        latest_before = set(LatestEntry.objects.filter(monitor=self.monitor).values_list('entry_type', 'entry_id', 'timestamp'))

        with pytest.raises(RuntimeError):
            restamp_through(self.monitor, end=days[-1], dry_run=False, api=fake_api(error_on=days[-1]))

        assert all_rows(self.monitor) == before
        latest_after = set(LatestEntry.objects.filter(monitor=self.monitor).values_list('entry_type', 'entry_id', 'timestamp'))
        assert latest_after == latest_before

    def test_other_stations_and_other_monitor_types_are_untouched(self):
        days = [date(2025, 7, 15), date(2025, 7, 16)]
        other = make_station('5')
        store_legacy(self.monitor, days)
        store_legacy(other, days)

        purple = Monitor.objects.get(pk='jLI5fer7S0uyR7eMYNSPpg')
        for hour in range(48):
            entry_models.Temperature.objects.create(
                monitor=purple,
                location=purple.location,
                timestamp=utc(days[0], hour),
                value=70,
            )
        other_before = all_rows(other)
        other_latest = set(LatestEntry.objects.filter(monitor=other).values_list('entry_type', 'entry_id', 'timestamp'))
        purple_before = rows(purple)

        # The response also carries the other station's records.
        restamp_through(self.monitor, end=days[-1], dry_run=False, api=fake_api(temp_offset=1))

        assert all_rows(other) == other_before
        assert set(LatestEntry.objects.filter(monitor=other).values_list('entry_type', 'entry_id', 'timestamp')) == other_latest
        assert rows(purple) == purple_before
        assert len(rows(self.monitor)) == 48

    fixtures = ['purple-air.yaml']

    def test_runs_through_today_and_keeps_todays_new_style_rows(self):
        # PST. Earlier days were stored the old way; today's first hours were
        # already written the new way by the live ingest, and the API answers
        # for today only with the hours so far. The window ends at the old
        # stamp of (today, 2400), 00:00 tomorrow: the new stamp of tomorrow's
        # 0100, which can't be stored yet, so nothing past the window is lost.
        days = [date(2025, 1, 14), date(2025, 1, 15)]
        today = date(2025, 1, 16)
        store_legacy(self.monitor, days)
        so_far = HOURS[:6]
        # Today's 0100 has the old stamp of yesterday's 2400 (00:00 PST), so
        # the live ingest couldn't write it; the restamp does.
        for hour in so_far[1:]:
            self.monitor.handle_payload(make_record(today, hour))
        assert len(rows(self.monitor)) == 48 + 5

        api = fake_api(hours={today: so_far})
        result = restamp_through(self.monitor, end=today, dry_run=False, api=api)

        assert result.end == today
        assert {call.kwargs['start_date'] for call in api.get_hourly_data.call_args_list} == {*days, today}
        expected = {
            (self.monitor.parse_timestamp(make_record(day, hour)), Decimal(make_record(day, hour)['HlyAirTmp']['Value']))
            for day, hours in [(days[0], HOURS), (days[1], HOURS), (today, so_far)] for hour in hours
        }
        assert rows(self.monitor) == expected
        _window_start, window_end = delete_window(self.monitor, days[0], today)
        assert window_end == self.monitor.parse_timestamp(make_record(today + timedelta(days=1), '0100'))

    def test_today_is_the_pacific_date(self):
        from camp.apps.monitors.cimis import restamp
        assert restamp.today() == localtime().date()

    def test_a_malformed_record_is_skipped_and_the_rest_written(self):
        days = [date(2025, 7, 15), date(2025, 7, 16)]
        store_legacy(self.monitor, days)
        bad = make_record(days[0], '0100')
        bad['Hour'] = 'xx00'

        with patch('camp.apps.monitors.cimis.restamp.sentry_sdk.capture_exception') as capture:
            result = restamp_through(self.monitor, end=days[-1], dry_run=False, api=fake_api(extra=[bad]))

        assert result.skipped == 1
        assert capture.call_count == 1
        assert result.labels == 49
        assert result.written == 96
        assert rows(self.monitor) == {
            (self.monitor.parse_timestamp(make_record(day, hour)), Decimal(make_record(day, hour)['HlyAirTmp']['Value']))
            for day in days for hour in HOURS
        }

    def test_a_short_answer_for_a_stored_date_leaves_the_station_untouched(self):
        days = [date(2025, 7, 15), date(2025, 7, 16), date(2025, 7, 17)]
        store_legacy(self.monitor, days)
        before = all_rows(self.monitor)

        for dry_run in (True, False):
            with pytest.raises(ShortAnswer, match='2025-07-16'):
                restamp_through(self.monitor, end=days[-1], dry_run=dry_run, api=fake_api(days={days[0], days[2]}))

        assert all_rows(self.monitor) == before

    def test_no_labels_for_a_date_with_nothing_stored_is_fine(self):
        days = [date(2025, 7, 15), date(2025, 7, 17)]
        store_legacy(self.monitor, days)

        result = restamp_through(self.monitor, end=days[-1], dry_run=False, api=fake_api(days=set(days)))

        assert result.labels == 48
        assert len(rows(self.monitor)) == 48


class RestampCommandTests(TestCase):
    def test_command_requires_monitor(self):
        with pytest.raises(CommandError):
            call_command('restamp_cimis', stdout=StringIO())

    def test_command_has_no_end_option(self):
        monitor = make_dash_station('2')
        with pytest.raises(CommandError, match='--end'):
            call_command('restamp_cimis', f'--monitor={monitor.pk}', '--end', '2025-07-16', stdout=StringIO())

    def test_command_reports_a_short_answer(self):
        monitor = make_dash_station('2')
        days = [date(2025, 7, 15), date(2025, 7, 16)]
        store_legacy(monitor, days)
        before = all_rows(monitor)
        err = StringIO()

        with patch('camp.apps.monitors.cimis.restamp.CIMISAPI', return_value=fake_api(days={days[0]})), through(days[-1]):
            with pytest.raises(CommandError, match=re.escape(str(monitor.pk))):
                call_command('restamp_cimis', f'--monitor={monitor.pk}', stdout=StringIO(), stderr=err)

        assert 'no labels' in err.getvalue()
        assert '2025-07-16' in err.getvalue()
        assert all_rows(monitor) == before

    def test_command_rejects_an_unknown_monitor(self):
        with pytest.raises(CommandError):
            call_command('restamp_cimis', '--monitor', 'nope', stdout=StringIO())

    def test_command_restamps_and_prints_counts(self):
        monitor = make_dash_station('2')
        days = [date(2025, 7, 15), date(2025, 7, 16)]
        store_legacy(monitor, days)
        out = StringIO()

        with patch('camp.apps.monitors.cimis.restamp.CIMISAPI', return_value=fake_api()), through(days[-1]):
            call_command('restamp_cimis', f'--monitor={monitor.pk}', stdout=out)

        output = out.getvalue()
        assert '2025-07-15' in output
        assert 'labels fetched: 48' in output
        assert 'temperature: 48' in output
        assert 'written: 96' in output
        assert 'skipped: 0' in output
        stamps = {timestamp for timestamp, _value in rows(monitor)}
        assert utc(days[0], 8) in stamps

    def test_command_dry_run_writes_nothing(self):
        monitor = make_dash_station('2')
        days = [date(2025, 7, 15), date(2025, 7, 16)]
        store_legacy(monitor, days)
        before = all_rows(monitor)
        out = StringIO()

        with patch('camp.apps.monitors.cimis.restamp.CIMISAPI', return_value=fake_api()), through(days[-1]):
            call_command('restamp_cimis', f'--monitor={monitor.pk}', '--dry-run', stdout=out)

        assert all_rows(monitor) == before
        assert 'dry run' in out.getvalue().lower()
