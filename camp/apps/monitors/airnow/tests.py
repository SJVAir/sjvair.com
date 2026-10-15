from unittest.mock import MagicMock, patch

from django.test import TestCase

import requests

from camp.apps.monitors.airnow.api import AirNowAPI


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


class ImportAirNowDataCommandTests(TestCase):
    def _call(self, *args):
        from datetime import datetime, timezone as dt_timezone
        from io import StringIO
        from django.core.management import call_command

        with patch('camp.apps.monitors.airnow.management.commands.import_airnow_data.import_airnow_data') as task:
            call_command('import_airnow_data', *args, stdout=StringIO())
        return task.call_local

    def test_no_options_keeps_default_window(self):
        call_local = self._call()
        call_local.assert_called_once_with(start_date=None, end_date=None)

    def test_start_and_end_are_passed_through_as_utc(self):
        from datetime import datetime, timezone as dt_timezone

        call_local = self._call('--start', '2026-07-24', '--end', '2026-08-12T06:00')
        call_local.assert_called_once_with(
            start_date=datetime(2026, 7, 24, tzinfo=dt_timezone.utc),
            end_date=datetime(2026, 8, 12, 6, tzinfo=dt_timezone.utc),
        )

    def test_offset_is_respected(self):
        from datetime import datetime, timedelta, timezone as dt_timezone

        call_local = self._call('--start', '2026-07-24T00:00-07:00')
        start = call_local.call_args.kwargs['start_date']
        assert start == datetime(2026, 7, 24, 7, tzinfo=dt_timezone.utc)
        assert call_local.call_args.kwargs['end_date'] is None

    def test_rejects_start_after_end(self):
        import pytest
        from django.core.management.base import CommandError

        with pytest.raises(CommandError):
            self._call('--start', '2026-08-12', '--end', '2026-07-24')

    def test_rejects_invalid_timestamp(self):
        import pytest
        from django.core.management.base import CommandError

        with pytest.raises(CommandError):
            self._call('--start', 'yesterday')

