from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from datetime import datetime, timedelta, timezone as dt_timezone

from django.contrib.gis.geos import GEOSGeometry, Point
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from django.utils.dateparse import parse_datetime

import requests

from camp.apps.calibrations import processors
from camp.apps.entries import models as entry_models
from camp.apps.monitors.airnow import backfill
from camp.apps.monitors.airnow.api import AirNowAPI
from camp.apps.monitors.airnow.models import AirNow
from camp.apps.monitors.models import Entry, LatestEntry
from camp.apps.regions.models import Boundary, Region
from camp.utils.datetime import make_aware


def make_response(status_code=200, json_result=None, json_error=None):
    response = MagicMock()
    response.status_code = status_code
    if json_error is not None:
        response.json.side_effect = json_error
    else:
        response.json.return_value = json_result
    return response


class FetchEntriesTests(TestCase):
    def setUp(self):
        self.client = AirNowAPI(api_key='test-key')

    @patch('camp.apps.monitors.airnow.api.time.sleep')
    @patch.object(AirNowAPI, 'data')
    def test_returns_entries_on_first_success(self, mock_data, mock_sleep):
        mock_data.return_value = make_response(json_result=[{'SiteName': 'A'}])

        entries = self.client.fetch_entries(bbox=(1, 2, 3, 4), start_date=None, end_date=None)

        assert entries == [{'SiteName': 'A'}]
        assert mock_data.call_count == 1
        mock_sleep.assert_not_called()

    @patch('camp.apps.monitors.airnow.api.time.sleep')
    @patch.object(AirNowAPI, 'data')
    def test_retries_on_bad_json_body_then_succeeds(self, mock_data, mock_sleep):
        json_error = requests.exceptions.JSONDecodeError('Expecting value', '', 0)
        mock_data.side_effect = [
            make_response(json_error=json_error),
            make_response(json_result=[{'SiteName': 'B'}]),
        ]

        entries = self.client.fetch_entries(bbox=(1, 2, 3, 4), start_date=None, end_date=None)

        assert entries == [{'SiteName': 'B'}]
        assert mock_data.call_count == 2
        mock_sleep.assert_called_once()

    @patch('camp.apps.monitors.airnow.api.time.sleep')
    @patch.object(AirNowAPI, 'data')
    def test_raises_after_exhausting_attempts_on_bad_json(self, mock_data, mock_sleep):
        json_error = requests.exceptions.JSONDecodeError('Expecting value', '', 0)
        mock_data.return_value = make_response(json_error=json_error)

        with self.assertRaises(requests.exceptions.JSONDecodeError):
            self.client.fetch_entries(
                bbox=(1, 2, 3, 4), start_date=None, end_date=None, max_attempts=3,
            )

        assert mock_data.call_count == 3

    @patch('camp.apps.monitors.airnow.api.time.sleep')
    @patch.object(AirNowAPI, 'data')
    def test_retries_on_rate_limit_then_succeeds(self, mock_data, mock_sleep):
        mock_data.side_effect = [
            make_response(status_code=429),
            make_response(json_result=[{'SiteName': 'C'}]),
        ]

        entries = self.client.fetch_entries(bbox=(1, 2, 3, 4), start_date=None, end_date=None)

        assert entries == [{'SiteName': 'C'}]
        assert mock_data.call_count == 2
        mock_sleep.assert_called_once()

    @patch('camp.apps.monitors.airnow.api.time.sleep')
    @patch.object(AirNowAPI, 'data')
    def test_raises_after_exhausting_attempts_on_rate_limit(self, mock_data, mock_sleep):
        response = make_response(status_code=429)
        response.raise_for_status.side_effect = requests.exceptions.HTTPError('429')
        mock_data.return_value = response

        with self.assertRaises(requests.exceptions.HTTPError):
            self.client.fetch_entries(
                bbox=(1, 2, 3, 4), start_date=None, end_date=None, max_attempts=2,
            )

        assert mock_data.call_count == 2


def make_payload(parameter, value, raw):
    return {
        'Parameter': parameter,
        'UTC': '2026-09-01T12:00',
        'Value': value,
        'RawConcentration': raw,
    }


class DataRequestTests(TestCase):
    @patch.object(AirNowAPI, 'request')
    def test_does_not_send_nowcastonly(self, mock_request):
        AirNowAPI(api_key='test-key').data(bbox=(1, 2, 3, 4), start_date=None, end_date=None)

        params = mock_request.call_args.kwargs['params']
        assert 'nowcastonly' not in params
        assert params['includerawconcentrations'] == 1


class ActiveTests(TestCase):
    def test_active_until_the_next_hours_raw_arrives(self):
        # The newest RAW is up to 2h20m old: an hour's RawConcentration
        # arrives about 1h20m after it starts.
        monitor = AirNow.objects.create(
            name='Fresno - Garland',
            position=Point(-119.7727, 36.7853, srid=4326),
            location=AirNow.LOCATION.outside,
        )
        hour = timezone.now().replace(minute=0, second=0, microsecond=0) - timedelta(hours=2)
        monitor.handle_payload(make_site_payload('OZONE', 41.0, 38.0, utc=hour.strftime('%Y-%m-%dT%H:%M')))

        with patch('django.utils.timezone.now', return_value=hour + timedelta(hours=2, minutes=20)):
            assert monitor.is_active
            assert AirNow.objects.get_active().filter(pk=monitor.pk).exists()


class HandlePayloadTests(TestCase):
    def setUp(self):
        self.monitor = AirNow.objects.create(
            name='Fresno - Garland',
            position=Point(-119.7727, 36.7853, srid=4326),
            location=AirNow.LOCATION.outside,
        )

    def test_pm25_uses_raw_concentration(self):
        entry = self.monitor.handle_payload(make_payload('PM2.5', 18.2, 14.0))

        assert isinstance(entry, entry_models.PM25)
        assert entry.value == Decimal('14.0')

    def test_ozone_uses_raw_concentration(self):
        entry = self.monitor.handle_payload(make_payload('OZONE', 41.0, 38.0))

        assert isinstance(entry, entry_models.O3)
        assert entry.value == Decimal('38.0')

    def test_other_parameters_use_value(self):
        entry = self.monitor.handle_payload(make_payload('NO2', 12.0, 12.0))

        assert isinstance(entry, entry_models.NO2)
        assert entry.value == Decimal('12.0')

    def test_pm10_uses_raw_concentration(self):
        entry = self.monitor.handle_payload(make_payload('PM10', 30.0, 25.0))

        assert isinstance(entry, entry_models.PM100)
        assert entry.value == Decimal('25.0')

    def test_missing_raw_not_stored(self):
        for parameter, EntryModel in [('PM2.5', entry_models.PM25), ('OZONE', entry_models.O3), ('NO2', entry_models.NO2)]:
            entry = self.monitor.handle_payload(make_payload(parameter, -999, -999))

            assert entry is None
            assert not EntryModel.objects.filter(monitor=self.monitor, stage=EntryModel.Stage.RAW).exists()

    def test_missing_raw_still_stores_nowcast(self):
        self.monitor.handle_payload(make_payload('OZONE', 41.0, -999))

        O3 = entry_models.O3
        assert not O3.objects.filter(monitor=self.monitor, stage=O3.Stage.RAW).exists()
        assert O3.objects.get(monitor=self.monitor, stage=O3.Stage.CALIBRATED).value == Decimal('41.0')

    def test_reimport_replaces_nowcast_value(self):
        # An entry stored before the fix, holding the NowCast.
        self.monitor.create_entry(
            entry_models.PM25,
            timestamp=make_aware(parse_datetime('2026-09-01T12:00')),
            value=18.2,
        )

        entry = self.monitor.handle_payload(make_payload('PM2.5', 18.2, 14.0))

        assert entry.value == Decimal('14.0')
        assert entry_models.PM25.objects.filter(monitor=self.monitor, stage='raw').count() == 1

    def test_legacy_entry_uses_raw_concentration(self):
        entry = self.monitor.process_entry(Entry(monitor=self.monitor), {
            'PM2.5': make_payload('PM2.5', 18.2, 14.0),
            'OZONE': make_payload('OZONE', 41.0, 38.0),
            'PM10': make_payload('PM10', 30.0, 25.0),
        })

        assert entry.pm25 == 14.0
        assert entry.ozone == 38.0
        assert entry.pm100 == 25.0


class NowCastTests(TestCase):
    def setUp(self):
        self.monitor = AirNow.objects.create(
            name='Fresno - Garland',
            position=Point(-119.7727, 36.7853, srid=4326),
            location=AirNow.LOCATION.outside,
        )

    def get_nowcast(self, EntryModel):
        return EntryModel.objects.filter(monitor=self.monitor, stage=EntryModel.Stage.CALIBRATED)

    def test_pm25_nowcast_stored_as_calibrated(self):
        self.monitor.handle_payload(make_payload('PM2.5', 18.2, 14.0))

        nowcast = self.get_nowcast(entry_models.PM25).get()
        assert nowcast.processor == 'PM25_AirNow_NowCast'
        assert nowcast.value == Decimal('18.2')

    def test_ozone_nowcast_stored_as_calibrated(self):
        self.monitor.handle_payload(make_payload('OZONE', 41.0, 38.0))

        nowcast = self.get_nowcast(entry_models.O3).get()
        assert nowcast.processor == 'O3_AirNow_NowCast'
        assert nowcast.value == Decimal('41.0')

    def test_missing_nowcast_not_stored(self):
        entry = self.monitor.handle_payload(make_payload('OZONE', -999, 38.0))

        assert entry.value == Decimal('38.0')
        assert not self.get_nowcast(entry_models.O3).exists()

    def test_raw_saved_before_nowcast(self):
        stages = []
        create_entry = self.monitor.create_entry

        def track(EntryModel, **data):
            stages.append(data.get('stage', EntryModel.Stage.RAW))
            return create_entry(EntryModel, **data)

        with patch.object(self.monitor, 'create_entry', side_effect=track):
            self.monitor.handle_payload(make_payload('PM2.5', 18.2, 14.0))

        assert stages == [entry_models.PM25.Stage.RAW, entry_models.PM25.Stage.CALIBRATED]

    def test_nowcast_origin_is_the_raw_entry(self):
        raw = self.monitor.handle_payload(make_payload('PM2.5', 18.2, 14.0))

        assert self.get_nowcast(entry_models.PM25).get().origin_id == raw.pk

    def test_nowcast_origin_set_when_raw_unchanged(self):
        # Whole-number values compare equal to the stored Decimal, so create_entry returns None.
        raw = self.monitor.handle_payload(make_payload('OZONE', 41, 38))
        assert self.monitor.handle_payload(make_payload('OZONE', 42, 38)) is None

        nowcast = self.get_nowcast(entry_models.O3).get()
        assert nowcast.value == Decimal('42')
        assert nowcast.origin_id == raw.pk

    def test_nowcast_without_raw_has_no_origin(self):
        self.monitor.handle_payload(make_payload('OZONE', 41.0, -999))

        assert self.get_nowcast(entry_models.O3).get().origin_id is None

    def test_nowcast_processor_skips_missing(self):
        assert processors.PM25_AirNow_NowCast.create_entry(self.monitor, make_payload('PM2.5', -999, 14.0)) is None
        assert processors.O3_AirNow_NowCast.create_entry(self.monitor, make_payload('OZONE', None, 38.0)) is None

        entry = processors.PM25_AirNow_NowCast.create_entry(self.monitor, make_payload('PM2.5', 18.2, 14.0))
        assert entry.stage == entry_models.PM25.Stage.CALIBRATED
        assert entry.value == Decimal('18.2')

    def test_pm10_nowcast_stored_as_calibrated(self):
        raw = self.monitor.handle_payload(make_payload('PM10', 30.0, 25.0))

        nowcast = self.get_nowcast(entry_models.PM100).get()
        assert nowcast.processor == 'PM100_AirNow_NowCast'
        assert nowcast.value == Decimal('30.0')
        assert nowcast.origin_id == raw.pk

    def test_no_nowcast_for_other_parameters(self):
        for parameter, EntryModel in [('CO', entry_models.CO), ('NO2', entry_models.NO2), ('SO2', entry_models.SO2)]:
            self.monitor.handle_payload(make_payload(parameter, 12.0, 12.0))

            assert not self.get_nowcast(EntryModel).exists()

    def test_reimport_updates_nowcast(self):
        self.monitor.handle_payload(make_payload('PM2.5', 18.2, 14.0))
        self.monitor.handle_payload(make_payload('PM2.5', 19.0, 14.0))

        assert self.get_nowcast(entry_models.PM25).get().value == Decimal('19.0')

    def test_nowcast_is_not_the_latest_entry(self):
        entry = self.monitor.handle_payload(make_payload('PM2.5', 18.2, 14.0))
        self.monitor.process_entry_ng(entry)

        latest = LatestEntry.objects.filter(monitor=self.monitor, entry_type='pm25')
        assert set(latest.values_list('stage', flat=True)) == {entry_models.PM25.Stage.CLEANED}
        assert latest.get().entry.value == Decimal('14.0')


FRESNO_COUNTY = 'MULTIPOLYGON (((-120.5 36.2, -118.4 36.2, -118.4 37.6, -120.5 37.6, -120.5 36.2)))'


def make_site_payload(parameter, value, raw, utc='2026-09-01T12:00', site='Fresno - Garland', lon=-119.7727, lat=36.7853):
    return {
        'Parameter': parameter,
        'UTC': utc,
        'Value': value,
        'RawConcentration': raw,
        'SiteName': site,
        'Longitude': lon,
        'Latitude': lat,
        'AgencyName': 'San Joaquin Valley APCD',
    }


class GetWindowsTests(TestCase):
    def test_windows_are_contiguous_inclusive_hours(self):
        start = datetime(2020, 1, 1, tzinfo=dt_timezone.utc)
        end = datetime(2020, 1, 20, tzinfo=dt_timezone.utc)

        windows = backfill.get_windows(start, end, window=timedelta(days=7))

        assert windows == [
            (datetime(2020, 1, 1, tzinfo=dt_timezone.utc), datetime(2020, 1, 7, 23, tzinfo=dt_timezone.utc)),
            (datetime(2020, 1, 8, tzinfo=dt_timezone.utc), datetime(2020, 1, 14, 23, tzinfo=dt_timezone.utc)),
            (datetime(2020, 1, 15, tzinfo=dt_timezone.utc), datetime(2020, 1, 19, 23, tzinfo=dt_timezone.utc)),
        ]

    def test_start_rounds_down_to_the_hour(self):
        start = datetime(2020, 1, 1, 5, 30, tzinfo=dt_timezone.utc)
        end = datetime(2020, 1, 1, 8, tzinfo=dt_timezone.utc)

        assert backfill.get_windows(start, end) == [
            (datetime(2020, 1, 1, 5, tzinfo=dt_timezone.utc), datetime(2020, 1, 1, 7, tzinfo=dt_timezone.utc)),
        ]


@patch('camp.apps.monitors.airnow.backfill.time.sleep')
@patch('camp.apps.monitors.airnow.backfill.airnow_api.fetch_entries')
class BackfillTests(TestCase):
    def setUp(self):
        region = Region.objects.create(name='Fresno County', slug='fresno', type=Region.Type.COUNTY, external_id='06019')
        region.boundary = Boundary.objects.create(
            region=region, version='2020', geometry=GEOSGeometry(FRESNO_COUNTY, srid=4326),
        )
        region.save()

        self.monitor = AirNow.objects.create(
            name='Fresno - Garland',
            position=Point(-119.7727, 36.7853, srid=4326),
            location=AirNow.LOCATION.outside,
        )
        self.timestamp = make_aware(parse_datetime('2026-09-01T12:00'))
        self.start = datetime(2026, 9, 1, 12, tzinfo=dt_timezone.utc)
        self.end = datetime(2026, 9, 1, 13, tzinfo=dt_timezone.utc)

    def get_entry(self, EntryModel, stage, **kwargs):
        return EntryModel.objects.get(monitor=self.monitor, timestamp=self.timestamp, stage=stage, **kwargs)

    def import_nowcast_era_entry(self, value):
        """Store RAW + CLEANED PM2.5 the way the import did before the fix: from the NowCast."""
        raw = self.monitor.create_entry(entry_models.PM25, timestamp=self.timestamp, value=value)
        return raw, self.monitor.process_entry_ng(raw)[0]

    def test_replaces_nowcast_raw_and_cleaned(self, mock_fetch, mock_sleep):
        _, old_cleaned = self.import_nowcast_era_entry(18.2)
        mock_fetch.return_value = [make_site_payload('PM2.5', 18.2, 14.0)]

        backfill.backfill_airnow(self.start, self.end)

        PM25 = entry_models.PM25
        assert self.get_entry(PM25, PM25.Stage.RAW).value == Decimal('14.0')
        cleaned = self.get_entry(PM25, PM25.Stage.CLEANED)
        assert cleaned.pk == old_cleaned.pk  # updated in place, so LatestEntry still points at it
        assert cleaned.value == Decimal('14.0')
        assert self.get_entry(PM25, PM25.Stage.CALIBRATED).value == Decimal('18.2')

    def test_creates_cleaned_when_missing(self, mock_fetch, mock_sleep):
        mock_fetch.return_value = [make_site_payload('PM2.5', 18.2, 14.0)]

        backfill.backfill_airnow(self.start, self.end)

        PM25 = entry_models.PM25
        assert self.get_entry(PM25, PM25.Stage.CLEANED).value == Decimal('14.0')

    def test_removes_cleaned_when_new_raw_is_invalid(self, mock_fetch, mock_sleep):
        _, old_cleaned = self.import_nowcast_era_entry(18.2)
        assert LatestEntry.objects.filter(entry_id=old_cleaned.pk).exists()
        mock_fetch.return_value = [make_site_payload('PM2.5', 18.2, -999)]

        backfill.backfill_airnow(self.start, self.end)

        PM25 = entry_models.PM25
        assert not PM25.objects.filter(pk=old_cleaned.pk).exists()
        assert not PM25.objects.filter(monitor=self.monitor, stage=PM25.Stage.RAW).exists()
        assert not LatestEntry.objects.filter(entry_id=old_cleaned.pk).exists()
        assert self.get_entry(PM25, PM25.Stage.CALIBRATED).value == Decimal('18.2')

    def test_removes_stored_missing_ozone(self, mock_fetch, mock_sleep):
        O3 = entry_models.O3
        old = self.monitor.create_entry(O3, timestamp=self.timestamp, value=-999)
        mock_fetch.return_value = [make_site_payload('OZONE', -999, -999)]

        totals = backfill.backfill_airnow(self.start, self.end)

        assert not O3.objects.filter(pk=old.pk).exists()
        assert not LatestEntry.objects.filter(entry_id=old.pk).exists()
        assert totals['missing'] == 1

    def test_ozone_raw_and_nowcast(self, mock_fetch, mock_sleep):
        mock_fetch.return_value = [make_site_payload('OZONE', 41.0, 38.0)]

        backfill.backfill_airnow(self.start, self.end)

        O3 = entry_models.O3
        assert self.get_entry(O3, O3.Stage.RAW).value == Decimal('38.0')
        assert self.get_entry(O3, O3.Stage.CALIBRATED).value == Decimal('41.0')

    def test_skips_new_sites_outside_the_valley(self, mock_fetch, mock_sleep):
        mock_fetch.return_value = [make_site_payload('PM2.5', 5.0, 5.0, site='Gilroy - 9th Street', lon=-121.57, lat=37.0)]

        totals = backfill.backfill_airnow(self.start, self.end)

        assert totals['skipped'] == 1
        assert not AirNow.objects.filter(name='Gilroy - 9th Street').exists()

    def test_creates_new_sites_inside_the_valley(self, mock_fetch, mock_sleep):
        mock_fetch.return_value = [make_site_payload('PM2.5', 5.0, 5.0, site='Fresno - Old Site', lon=-119.8, lat=36.8)]

        backfill.backfill_airnow(self.start, self.end)

        assert AirNow.objects.filter(name='Fresno - Old Site').exists()

    def test_other_parameters_imported(self, mock_fetch, mock_sleep):
        mock_fetch.return_value = [
            make_site_payload('PM10', 30.0, 25.0),
            make_site_payload('NO2', 12.0, 12.0),
        ]

        backfill.backfill_airnow(self.start, self.end)

        assert self.get_entry(entry_models.PM100, entry_models.PM100.Stage.RAW).value == Decimal('25.0')
        assert self.get_entry(entry_models.PM100, entry_models.PM100.Stage.CALIBRATED).value == Decimal('30.0')
        assert self.get_entry(entry_models.NO2, entry_models.NO2.Stage.RAW).value == Decimal('12.0')

    def test_pauses_after_each_request(self, mock_fetch, mock_sleep):
        mock_fetch.return_value = []

        backfill.backfill_airnow(self.start, self.start + backfill.WINDOW * 3, pause=8)

        assert mock_fetch.call_count == 3
        assert mock_sleep.call_count == 3
        mock_sleep.assert_called_with(8)

    def test_splits_window_over_record_limit(self, mock_fetch, mock_sleep):
        limit = {'WebServiceError': [{'Message': 'This query exceeds the record query limit. Please narrow the date range.'}]}
        mock_fetch.side_effect = [limit, [make_site_payload('PM2.5', 18.2, 14.0)], []]
        end = self.start + timedelta(hours=4)

        totals = backfill.backfill_airnow(self.start, end)

        windows = [(c.kwargs['start_date'], c.kwargs['end_date']) for c in mock_fetch.call_args_list]
        assert windows == [
            (self.start, self.start + timedelta(hours=3)),
            (self.start, self.start + timedelta(hours=1)),
            (self.start + timedelta(hours=2), self.start + timedelta(hours=3)),
        ]
        assert totals['entries'] == 1

    def test_raises_on_other_api_errors(self, mock_fetch, mock_sleep):
        mock_fetch.return_value = {'WebServiceError': [{'Message': 'Invalid API key.'}]}

        with pytest.raises(backfill.AirNowError, match='Invalid API key'):
            backfill.backfill_airnow(self.start, self.end)

    def test_rerun_is_idempotent(self, mock_fetch, mock_sleep):
        mock_fetch.return_value = [make_site_payload('PM2.5', 18.2, 14.0)]

        backfill.backfill_airnow(self.start, self.end)
        backfill.backfill_airnow(self.start, self.end)

        assert entry_models.PM25.objects.filter(monitor=self.monitor).count() == 3

    def hourly_payloads(self, hours):
        return [
            make_site_payload('PM2.5', 18.2 + hour, 14.1 + hour, utc=f'2026-09-01T{hour:02d}:00')
            for hour in range(hours)
        ]

    def count_queries(self, mock_fetch, hours):
        mock_fetch.return_value = self.hourly_payloads(hours)
        start = datetime(2026, 9, 1, tzinfo=dt_timezone.utc)
        backfill.backfill_airnow(start, start + timedelta(hours=hours))  # creates
        with CaptureQueriesContext(connection) as queries:
            backfill.backfill_airnow(start, start + timedelta(hours=hours))  # loads and compares
        return len(queries)

    def test_queries_dont_grow_with_the_hours_in_a_window(self, mock_fetch, mock_sleep):
        assert self.count_queries(mock_fetch, 3) == self.count_queries(mock_fetch, 24)

    def test_unchanged_rerun_writes_nothing(self, mock_fetch, mock_sleep):
        mock_fetch.return_value = self.hourly_payloads(6)
        start = datetime(2026, 9, 1, tzinfo=dt_timezone.utc)
        backfill.backfill_airnow(start, start + timedelta(hours=6))
        modified = dict(entry_models.PM25.objects.values_list('pk', 'modified'))

        with CaptureQueriesContext(connection) as queries:
            backfill.backfill_airnow(start, start + timedelta(hours=6))

        assert dict(entry_models.PM25.objects.values_list('pk', 'modified')) == modified
        assert not [q for q in queries if q['sql'].startswith(('INSERT', 'UPDATE "entries', 'DELETE'))]

    def test_latest_entry_is_the_newest_hour(self, mock_fetch, mock_sleep):
        mock_fetch.return_value = self.hourly_payloads(6)
        start = datetime(2026, 9, 1, tzinfo=dt_timezone.utc)

        backfill.backfill_airnow(start, start + timedelta(hours=6))

        PM25 = entry_models.PM25
        latest = LatestEntry.objects.get(monitor=self.monitor, stage=PM25.Stage.CLEANED)
        assert latest.timestamp == start + timedelta(hours=5)
        assert PM25.objects.get(pk=latest.entry_id).value == Decimal('19.10')

    def test_cleaned_points_at_its_raw(self, mock_fetch, mock_sleep):
        mock_fetch.return_value = [make_site_payload('PM2.5', 18.2, 14.0)]

        backfill.backfill_airnow(self.start, self.end)

        PM25 = entry_models.PM25
        raw = self.get_entry(PM25, PM25.Stage.RAW)
        assert self.get_entry(PM25, PM25.Stage.CLEANED).origin_id == raw.pk
        assert self.get_entry(PM25, PM25.Stage.CALIBRATED).origin_id == raw.pk
